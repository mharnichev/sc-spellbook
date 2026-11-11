#!/usr/bin/env python3
"""Private, fail-closed dispatch fence. Never calls a provider."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import time


SOURCE = '0158_shop_alert_intents'
HEAD = '0158_shop_alert_intents'
FLAG = 'MASTER_MONO_INVOICE_CREATE_ENABLED'
REFUND_FLAG = 'SHOP_MONO_CHECKBOX_REFUNDS_ENABLED'
CHECKOUT_FLAGS = ('SHOP_CHECKOUT_ENABLED', 'SHOP_CHECKOUT_PILOT_ENABLED')
WRITERS = ('backend', 'booking-sms-reminders')


class CutoverInterrupted(BaseException):
    pass


def install_signal_handlers():
    def interrupted(number, frame):
        # Do not let a second catchable termination interrupt the bounded cleanup.
        for value in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            signal.signal(value, signal.SIG_IGN)
        raise CutoverInterrupted()
    return {value: signal.signal(value, interrupted) for value in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def private_bytes(path):
    require(not path.is_symlink(), 'Private file must not be a symlink')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600, 'Private owned mode600 file required')
        return stream.read()


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def persist(path, value, exclusive=False):
    data = json.dumps(value, sort_keys=True).encode() + b'\n'
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
    else:
        atomic_bytes(path, data)
    sync_directory(path.parent)


def atomic_bytes(path, data):
    fd, name = tempfile.mkstemp(prefix='.cutover-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def paused_env(data):
    assignments = re.findall(rb'(?im)^[ \t]*(?:export[ \t]+)?' + FLAG.encode() + rb'[ \t]*=', data)
    pattern = rb'(?im)^([ \t]*(?:export[ \t]+)?' + FLAG.encode() + rb'[ \t]*=[ \t]*)(true|false|1|0)([ \t]*(?:#[^\r\n]*)?\r?)$'
    require(len(assignments) == 1 and len(re.findall(pattern, data)) == 1,
            'Exactly one explicit boolean create flag assignment required')
    return re.sub(pattern, lambda match: match[1] + b'false' + match[3], data)


def cas_env(path, expected, replacement):
    require(private_bytes(path) == expected, 'Backend configuration drift; no overwrite performed')
    # All cooperating release/config writers must hold the existing release mutex.
    atomic_bytes(path, replacement)
    require(private_bytes(path) == replacement, 'Configuration replacement could not be verified')


def verify_flags(original, actual, paused):
    require(FLAG in original and type(original[FLAG]) is bool, 'Effective create flag missing')
    expected = {**original, FLAG: False} if paused else original
    require(actual == expected, 'Effective flags differ from the exact reviewed phase')



def verify_candidate_flags(original, candidate, writer):
    require(candidate.get(REFUND_FLAG) is False, 'Candidate must disable live refunds')
    if writer == 'backend':
        require(all(candidate.get(flag) is False for flag in CHECKOUT_FLAGS),
                'Candidate API must keep checkout and its pilot closed')
    expected = {**original, REFUND_FLAG: False}
    require(all(flag in candidate and candidate[flag] == value for flag, value in expected.items()
                if flag not in CHECKOUT_FLAGS), 'Candidate changes existing writer flags')
    require(all(value is False for flag, value in candidate.items() if flag not in expected
                and flag not in CHECKOUT_FLAGS), 'New writer flags must default off')


def verify_drain(before, after):
    expected = [(1, 3), (2, 4)]
    require([(row['id'], row['order_id']) for row in before['unresolved']] == expected,
            'Historical unresolved requests are not exactly request1/order3 and request2/order4')
    require(before['head'] in (SOURCE, HEAD) and after['head'] == before['head']
            and after['sessions'] == 0, 'Captured schema or writer session drain failed')
    for snapshot in (before, after):
        require(snapshot['closures'] == 2 and snapshot['closure_orders'] == [5, 6]
                and snapshot['conflicts'] == 0, 'Protected closure5/6 or quarantine baseline differs')
    for key in ('unresolved', 'requests', 'protected', 'compatibility', 'closure_orders', 'closures', 'conflicts'):
        require(before[key] == after[key], 'Dispatch or protected ledger changed during drain: ' + key)


def verify_shutdown(info, logs, events, api=False):
    state = info['State']
    require(state['Running'] is False and state['ExitCode'] == 0 and not state['OOMKilled']
            and not state.get('Error') and state['FinishedAt'] > state['StartedAt'],
            'Writer shutdown is not clean; inspect before recovery')
    require(not any(event.get('Action') == 'oom' or (
        event.get('Action') == 'kill' and str(event.get('Actor', {}).get('Attributes', {}).get('signal')) in ('9', 'SIGKILL'))
        for event in events), 'Forced writer termination detected')
    require(not api or b'Application shutdown complete.' in logs,
            'API graceful shutdown log evidence missing')


def snapshot_sql(lease=None):
    verified_lease = "SELECT NULL::integer AS pid WHERE false"
    if lease is not None:
        pid, start_us = lease
        require(type(pid) is int and 0 < pid <= 2147483647
                and isinstance(start_us, str) and re.fullmatch(r'[1-9][0-9]{14,17}', start_us),
                'Invalid paired advisory lease identity')
        verified_lease = f"""
SELECT a.pid FROM pg_catalog.pg_stat_activity a
WHERE a.pid={pid} AND a.pid<>pg_backend_pid()
  AND ((extract(epoch FROM a.backend_start)*1000000)::numeric(20,0))::text='{start_us}'
  AND a.datname=current_database() AND a.usename=current_user AND a.backend_type='client backend'
  AND (SELECT count(*) FROM pg_catalog.pg_locks l WHERE l.pid=a.pid AND l.locktype='advisory'
       AND l.granted AND l.mode='ExclusiveLock'
       AND ((l.objsubid=2 AND (l.classid,l.objid) IN ((1396919372,13),(150,7)))
         OR (l.objsubid=1 AND l.classid=1 AND l.objid=2835491905)))=3
"""
    groups = [('orders', 'id'), ('order_items', 'order_id'), ('order_intents', 'order_id'),
              ('master_mono_create_requests', 'order_id'), ('master_mono_bindings', 'order_id'),
              ('order_payments', 'order_id'), ('fiscal_documents', 'order_id'),
              ('order_handovers', 'order_id'), ('inventory_movements', 'order_id'),
              ('master_mono_expired_closures', 'order_id'), ('master_mono_closed_conflicts', 'order_id')]
    # Hash complete rows; never export provider URLs, identifiers, evidence or PII.
    fields = []
    def fingerprint(table, condition, row='to_jsonb(t)'):
        return (
            f"'{table}',(SELECT json_build_object('count',count(*),"
            " 'hash',md5(coalesce(string_agg(row_hash,'' ORDER BY row_hash),'')))"
            f" FROM (SELECT md5(({row})::text) row_hash FROM public.{table} t WHERE {condition}) s)"
        )

    fields.extend(fingerprint(table, f't.{key} IN (3,4,5,6)') for table, key in groups)
    fields.append("'stock',(SELECT json_agg(t ORDER BY id) FROM (SELECT id,stock_quantity,reserved_quantity FROM products WHERE id IN (248,277)) t)")
    order8 = [fingerprint('orders', 't.id = 8')]
    for table in (
        'order_items', 'inventory_movements', 'order_intents', 'order_payments',
        'shop_payment_intents', 'shop_online_payment_requests', 'shop_operation_audits',
        'shop_payment_evidence', 'shop_payment_resolution_cases', 'shop_payment_confirmations',
        'shop_mono_checkbox_receipts', 'shop_mono_checkbox_observations', 'shop_checkbox_documents',
        'order_shipments', 'order_handovers', 'fiscal_documents',
    ):
        condition = 't.order_id = 8'
        if table in ('shop_online_payment_requests', 'shop_payment_evidence', 'shop_payment_resolution_cases'):
            condition += ' OR t.intent_id IN (SELECT id FROM public.shop_payment_intents WHERE order_id = 8)'
        order8.append(fingerprint(table, condition))
    order8.append(fingerprint(
        'products', 't.id IN (SELECT product_id FROM public.order_items WHERE order_id = 8)',
        'jsonb_build_array(t.id,t.stock_quantity,t.reserved_quantity)',
    ))
    fields.append("'shop_order_8',json_build_object(" + ','.join(order8) + ')')
    return """BEGIN READ ONLY; SET LOCAL statement_timeout='8s';
WITH verified_lease AS MATERIALIZED (""" + verified_lease + """)
SELECT json_build_object(
 'head',(SELECT version_num FROM alembic_version), 'watermark',clock_timestamp(),
 'lease_verified',EXISTS(SELECT FROM verified_lease),
 'sessions',(SELECT count(*) FROM pg_stat_activity a WHERE datname=current_database()
             AND backend_type='client backend' AND a.pid<>pg_backend_pid()
             AND NOT EXISTS(SELECT FROM verified_lease v WHERE v.pid=a.pid)),
 'requests',(SELECT md5(coalesce(string_agg(row_hash,'' ORDER BY row_hash),'')) FROM (SELECT md5(to_jsonb(q)::text) row_hash FROM master_mono_create_requests q) s),
 'compatibility',(SELECT json_object_agg(name,hash) FROM (
   SELECT 'bound' name,md5(coalesce(string_agg(row_hash,'' ORDER BY row_hash),'')) hash FROM (SELECT md5(to_jsonb(b)::text) row_hash FROM master_mono_bindings b) s
   UNION ALL SELECT 'prepared_intents',md5(coalesce(string_agg(row_hash,'' ORDER BY row_hash),'')) FROM (SELECT md5(to_jsonb(i)::text) row_hash FROM order_intents i) s) compatibility),
 'unresolved',(SELECT coalesce(json_agg(t ORDER BY id),'[]') FROM (
   SELECT q.id,q.order_id,md5(to_jsonb(q)::text) hash FROM master_mono_create_requests q
   WHERE NOT EXISTS(SELECT 1 FROM master_mono_bindings b WHERE b.create_request_id=q.id AND b.order_id=q.order_id)
     AND NOT EXISTS(SELECT 1 FROM master_mono_expired_closures c WHERE c.request_id=q.id AND c.order_id=q.order_id)) t),
 'closures',(SELECT count(*) FROM master_mono_expired_closures),
 'closure_orders',(SELECT json_agg(order_id ORDER BY order_id) FROM master_mono_expired_closures),
 'conflicts',(SELECT count(*) FROM master_mono_closed_conflicts),
 'protected',json_build_object(""" + ','.join(fields) + ")) ; ROLLBACK;"


# Read only boolean Settings; none of the secret-valued configuration is emitted.
FLAGS_CODE = """import os
from pathlib import Path
for entry in Path('/proc/1/environ').read_bytes().split(b'\\0'):
 if b'=' in entry:
  k,v=entry.split(b'=',1);os.environ[k.decode()]=v.decode()
"""
SETTINGS_FLAGS_CODE = """import json
from app.core.config import Settings
s=Settings()
print(json.dumps({k:v for k,v in s.model_dump(by_alias=True).items() if type(v) is bool}))
"""


class Cutover:
    def __init__(self, release, app):
        self.release, self.app = release.resolve(strict=True), app.resolve(strict=True)
        require(self.release.parent == self.app / 'releases', 'Exact release directory required')
        self.env = self.app / 'env/backend.env'
        require(os.environ.get('BACKEND_ENV_FILE', str(self.env)) == str(self.env), 'Backend env override refused')
        require(not os.environ.get('COMPOSE_FILE') and not os.environ.get('COMPOSE_PROFILES'), 'Compose override refused')
        self.directory = self.app / 'backups' / ('dispatch-cutover-' + self.release.name)
        self.journal = self.directory / 'journal.json'
        self.marker = self.app / 'backend-recovery-required'
        self.compose = ['docker', 'compose', '--project-name', os.environ.get('COMPOSE_PROJECT_NAME', 'soulcuts'),
                        '--env-file', str(self.release / 'versions/production.env'), '-f', str(self.release / 'docker-compose.prod.yml')]
        pins = (self.release / 'versions/production.env').read_text().splitlines()
        backend = [line.split('=', 1)[1] for line in pins if line.startswith('BACKEND_IMAGE=')]
        require(len(backend) == 1 and re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', backend[0]), 'Exact immutable backend pin required')
        self.backend_pin = backend[0]

    def run(self, command, data=None):
        result = subprocess.run(command, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
                                env={**os.environ, 'BACKEND_IMAGE': self.backend_pin})
        require(result.returncode == 0, 'Cutover command failed; no private output emitted')
        return result.stdout + result.stderr if command[:2] == ['docker', 'logs'] else result.stdout

    def service(self, name):
        value = self.run(self.compose + ['ps', '-a', '-q', name]).decode().strip()
        require(re.fullmatch('[0-9a-f]{64}', value), 'Exactly one full container identity required')
        info, = json.loads(self.run(['docker', 'inspect', value]))
        labels = info['Config']['Labels']
        require(labels['com.docker.compose.service'] == name and labels['com.docker.compose.project'] == self.compose[3],
                'Unexpected writer ownership')
        return info

    def flags(self, info):
        return json.loads(self.run(['docker', 'exec', info['Id'], 'python', '-c', FLAGS_CODE + SETTINGS_FLAGS_CODE]))

    def candidate_flags(self):
        services = json.loads(self.run(self.compose + ['config', '--format', 'json']))['services']
        # The running backend owns a static ingress address. Probe settings offline.
        code = 'import json, os, sys\nos.environ.update(json.load(sys.stdin))\n' + SETTINGS_FLAGS_CODE
        command = ['docker', 'run', '--rm', '-i', '--pull=never', '--network', 'none',
                   '--entrypoint', 'python', self.backend_pin, '-c', code]
        return {name: json.loads(self.run(command, json.dumps(services[name]['environment']).encode()))
                for name in WRITERS}

    def snapshot(self):
        pid = os.environ.get('CUTOVER_LEASE_PID', '')
        require(re.fullmatch(r'[1-9][0-9]{0,9}', pid), 'Paired advisory lease PID required')
        lease = int(pid), os.environ.get('CUTOVER_LEASE_START_US', '')
        postgres = self.service('postgres')['Id']
        result = json.loads(self.run(['docker', 'exec', '-i', postgres, 'sh', '-c',
            'exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'], snapshot_sql(lease).encode()))
        require(result['lease_verified'] is True, 'Paired advisory lease missing or lost')
        return result

    def verify_lease(self):
        require(self.snapshot()['lease_verified'] is True, 'Paired advisory lease required')

    def load(self, allow_accepted_current=False):
        require(not self.directory.is_symlink() and self.directory.stat().st_uid == os.geteuid()
                and stat.S_IMODE(self.directory.stat().st_mode) == 0o700, 'Private cutover directory required')
        state = json.loads(private_bytes(self.journal))
        require(state['release'] == str(self.release) and state['pins_hash'] == digest((self.release / 'versions/production.env').read_bytes()),
                'Cutover release or pins changed')
        current = str((self.app / 'current').resolve(strict=True))
        if current != state['previous']:
            require(allow_accepted_current and current == str(self.release) and state.get('acceptance_started') is True
                    and state['phase'] in ('accepting', 'accepted', 'recovery_required', 'paused_verified', 'resume_intent', 'resumed'),
                    'Accepted release changed outside the journaled acceptance transition')
            if state['phase'] != 'accepted' or self.marker.exists():
                self.marker_matches()
        return state

    def save(self, state, phase):
        state['phase'] = phase
        persist(self.journal, state)

    def marker_matches(self):
        fields = dict(line.split('=', 1) for line in private_bytes(self.marker).decode().splitlines() if '=' in line)
        require(fields.get('release') == str(self.release), 'Recovery marker belongs to another release')
        return fields

    def original(self, state):
        original = private_bytes(self.directory / 'original.env')
        require(digest(original) == state['original_hash'] and digest(paused_env(original)) == state['paused_hash'],
                'Private config checkpoint changed')
        return original

    def verify_no_other_recovery(self):
        for name in ('master-qr-activation-required', 'english-backfill-required',
                     'shop-online-activation-required'):
            require(not os.path.lexists(self.app / name), 'Another recovery must finish before release')

    def prepare(self):
        self.verify_no_other_recovery()
        if os.path.lexists(self.directory):
            raise FileExistsError('Cutover journal directory already exists')
        original = private_bytes(self.env)
        paused = paused_env(original)
        writers = {name: self.service(name) for name in WRITERS}
        flags = {name: self.flags(info) for name, info in writers.items()}
        target_flags = self.candidate_flags()
        for name in WRITERS:
            verify_candidate_flags(flags[name], target_flags[name], name)
        require(all(info['State']['Running'] for info in writers.values()), 'Old writers must be running at capture')
        baseline = self.snapshot()
        verify_drain(baseline, {**baseline, 'sessions': 0})
        state = dict(release=str(self.release), previous=str((self.app / 'current').resolve(strict=True)),
                     pins_hash=digest((self.release / 'versions/production.env').read_bytes()),
                     original_hash=digest(original), paused_hash=digest(paused), target_flags=target_flags,
                     writers={name: {'id': info['Id'], 'started': info['State']['StartedAt']} for name, info in writers.items()},
                     baseline=baseline, phase='prepared', captured=int(time.time()))
        for name in WRITERS:
            verify_flags(flags[name], flags[name], paused=False)
            value = re.search(rb'(?im)^[ \t]*(?:export[ \t]+)?' + FLAG.encode() + rb'[ \t]*=[ \t]*(true|false|1|0)', original)[1]
            require(flags[name][FLAG] == (value.lower() in (b'true', b'1')), 'Original file and old process create flag differ')
        self.directory.mkdir(mode=0o700)
        sync_directory(self.directory.parent)
        atomic_bytes(self.directory / 'original.env', original)
        persist(self.journal, state, exclusive=True)

    def pause(self, reconcile=False):
        state = self.load(); self.marker_matches()
        require(state['phase'] == 'prepared' or (reconcile and state['phase'] in ('pause_intent', 'paused')),
                'Pause already attempted; inspect instead of repeating')
        for name in WRITERS:
            info = self.service(name)
            require(info['Id'] == state['writers'][name]['id'] and info['State']['StartedAt'] == state['writers'][name]['started'],
                    'Old writer identity or start timestamp changed')
            events = [json.loads(line) for line in self.run(['docker', 'events', '--since', str(state['captured']),
                      '--until', datetime.datetime.now(datetime.UTC).isoformat(), '--filter', 'container=' + info['Id'], '--format', '{{json .}}']).splitlines()]
            logs = self.run(['docker', 'logs', '--since', info['State']['StartedAt'], info['Id']])
            verify_shutdown(info, logs, events, api=name == 'backend')
            state['writers'][name]['shutdown_logs_sha256'] = digest(logs)
        drained = self.snapshot(); verify_drain(state['baseline'], drained)
        self.save(state, 'pause_intent')
        original = self.original(state)
        if not reconcile or private_bytes(self.env) != paused_env(original):
            cas_env(self.env, original, paused_env(original))
        verify_drain(drained, self.snapshot())
        self.save(state, 'paused')

    def verify_live(self, state, paused, previous_ids):
        fields = self.marker_matches()
        require(fields.get('phase') == 'pending_acceptance', 'Pending acceptance required')
        original = self.original(state)
        require(private_bytes(self.env) == (paused_env(original) if paused else original), 'Config differs from phase')
        self.run(['python3', str(self.release / 'scripts/verify-deployed-images.py')])
        self.run(['bash', str(self.release / 'scripts/verify-background-owner.sh')])
        ids = {}
        for name in WRITERS:
            info = self.service(name)
            require(info['Id'] != previous_ids[name] and info['State']['Running']
                    and (name != 'backend' or (info['State'].get('Health') or {}).get('Status') == 'healthy'),
                    'New healthy writer identity required')
            verify_flags(state['target_flags'][name], self.flags(info), paused)
            ids[name] = info['Id']
        after = self.snapshot()
        require(after['head'] == HEAD, 'Exact target schema required')
        for key in ('requests', 'unresolved', 'protected', 'compatibility', 'closures', 'closure_orders', 'conflicts'):
            require(after[key] == state['baseline'][key], 'Protected dispatch history changed: ' + key)
        return ids

    def paused(self):
        state = self.load()
        require(state['phase'] == 'paused', 'Expected paused migration checkpoint')
        ids = self.verify_live(state, True, {name: state['writers'][name]['id'] for name in WRITERS})
        state['paused_ids'] = ids
        self.save(state, 'paused_verified')

    def verify_backup(self):
        fields = self.marker_matches()
        backup = Path(fields['backup']).resolve(strict=True)
        require(backup.parent == (self.app / 'backups').resolve() and not backup.stat().st_mode & 0o077,
                'Private paired backup required')
        manifest = json.loads(private_bytes(backup / 'manifest.json'))
        require(len(manifest) == 2 and len(list(backup.glob('*.dump'))) == 1 and len(list(backup.glob('*.tar.gz'))) == 1,
                'Paired DB/media backup required')
        require(set(manifest) == {path.name for pattern in ('*.dump', '*.tar.gz') for path in backup.glob(pattern)},
                'Manifest must cover the exact paired archives')
        for name, expected in manifest.items():
            path = backup / name
            require(path.parent == backup, 'Unexpected backup path')
            data = private_bytes(path)
            require(len(data) == expected['bytes'] > 0 and digest(data) == expected['sha256'], 'Backup checksum differs')

    def resume_under_lock(self):
        self.resume(server_verified=True)

    def resume(self, *, server_verified=False):
        # current=new is admitted only after the explicit journaled acceptance transition.
        state = self.load(allow_accepted_current=True)
        require(state['phase'] == 'paused_verified', 'Resume requires a verified paused pair; inspect instead of repeat')
        if not server_verified:
            require(os.environ.get('PILOT_MANUAL_GATE') == 'verified' and os.environ.get('EXPECTED_RELEASE') == str(self.release),
                    'Exact release recovery gate required')
        ids = self.verify_live(state, True, {name: state['writers'][name]['id'] for name in WRITERS})
        require(ids == state['paused_ids'], 'Paused writers changed since verification')
        self.verify_backup()
        original = self.original(state)
        self.save(state, 'resume_intent')
        try:
            cas_env(self.env, paused_env(original), original)
            self.start_writers()
            state['resumed_ids'] = self.verify_live(state, False, state['paused_ids'])
            self.save(state, 'resumed')
        except BaseException:
            self.fence_failed_pair(state)
            raise

    def fence_failed_pair(self, state):
        # Even a journal write failure must not bypass stop/refence. Never enable in finally.
        previous = {value: signal.signal(value, signal.SIG_IGN)
                    for value in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)}
        try:
            try:
                self.save(state, 'recovery_required')
            finally:
                try:
                    self.run(self.compose + ['stop', '--timeout', '90', *WRITERS])
                finally:
                    original = self.original(state)
                    current = private_bytes(self.env)
                    if current == original:
                        cas_env(self.env, original, paused_env(original))
                    else:
                        require(current == paused_env(original), 'Configuration drift; no recovery overwrite')
        finally:
            for value, handler in previous.items():
                signal.signal(value, handler)

    def refence(self):
        state = self.load(allow_accepted_current=True); self.marker_matches()
        require(state['phase'] in ('paused_verified', 'resume_intent', 'resumed', 'accepting', 'accepted', 'recovery_required'),
                'No verified new pair to refence')
        self.fence_failed_pair(state)

    def start_writers(self):
        self.run(self.compose + ['up', '-d', '--no-deps', '--force-recreate', *WRITERS])
        for attempt in range(36):
            if (self.service('backend')['State'].get('Health') or {}).get('Status') == 'healthy' and self.service('booking-sms-reminders')['State']['Running']:
                return
            time.sleep(2)
        raise RuntimeError('New writer health deadline exceeded')

    def recover_paused(self):
        state = self.load(allow_accepted_current=True); self.marker_matches()
        require(os.environ.get('PILOT_MANUAL_GATE') == 'verified' and os.environ.get('EXPECTED_RELEASE') == str(self.release),
                'Exact release inspected recovery gate required')
        head = self.snapshot()['head']
        baseline_head = state['baseline']['head']
        require(baseline_head in (SOURCE, HEAD) and head in (SOURCE, HEAD)
                and (baseline_head != HEAD or head == HEAD), 'Unknown or regressed schema; no recovery action performed')
        if head != HEAD or (baseline_head == HEAD and state['phase'] in ('prepared', 'pause_intent')):
            require(state['phase'] in ('prepared', 'pause_intent', 'paused'), 'Unexpected source-schema recovery phase')
            self.run(self.compose + ['stop', '--timeout', '90', *WRITERS])
            self.pause(reconcile=True)
            # Backup/migration must be separately reconciled. Never start the old producer.
            return
        require(state['phase'] in ('paused', 'paused_verified', 'resume_intent', 'accepting', 'accepted', 'recovery_required'),
                'Unexpected target-schema recovery phase')
        self.fence_failed_pair(state)
        stopped = self.snapshot()
        require(stopped['head'] == HEAD and stopped['sessions'] == 0, 'Target schema or writer session drain failed during recovery')
        for key in ('requests', 'unresolved', 'protected', 'compatibility', 'closures', 'closure_orders', 'conflicts'):
            require(stopped[key] == state['baseline'][key], 'Changed dispatch history requires investigation: ' + key)
        require(self.marker_matches().get('phase') == 'pending_acceptance', 'Pending acceptance required')
        self.verify_backup()
        try:
            self.start_writers()
            state['paused_ids'] = self.verify_live(state, True, {name: state['writers'][name]['id'] for name in WRITERS})
            self.save(state, 'paused_verified')
        except BaseException:
            self.run(self.compose + ['stop', '--timeout', '90', *WRITERS])
            raise

    def accepted(self):
        self.verify_no_other_recovery()
        state = self.load(allow_accepted_current=True)
        require(state['phase'] in ('resumed', 'accepting', 'accepted'), 'Acceptance requires verified resumed cutover')
        ids = self.verify_live(state, False, {name: state['writers'][name]['id'] for name in WRITERS})
        require(ids == state['resumed_ids'], 'Resumed writers replaced since verification')
        self.verify_backup()
        state['acceptance_started'] = True
        self.save(state, 'accepting')

    def switched(self):
        state = self.load(allow_accepted_current=True)
        require(state['phase'] == 'accepting' and (self.app / 'current').resolve() == self.release,
                'Exact journaled current switch required')
        require(self.marker_matches().get('phase') == 'pending_acceptance', 'Pending acceptance marker required')
        self.verify_lease()
        self.save(state, 'accepted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('schema-pair', 'verify-lease', 'prepare', 'pause', 'paused', 'resume', 'resume-under-lock', 'accepted', 'switched', 'inspect', 'recover-paused', 'refence'))
    parser.add_argument('--release', type=Path)
    args = parser.parse_args()
    if args.mode == 'schema-pair':
        print(SOURCE, HEAD)
        return
    if args.release is None:
        parser.error('--release is required')
    install_signal_handlers()
    os.umask(0o077)
    job = Cutover(args.release, Path(os.environ.get('APP_DIR', '/opt/soulcuts')))
    lock = job.app / 'release.lock'
    owns_lock = args.mode in ('resume', 'inspect', 'recover-paused')
    if owns_lock:
        lock.mkdir()
        (lock / 'pid').write_text(str(os.getpid()) + '\n')
    else:
        require(int((lock / 'pid').read_text()) == os.getppid(), 'Existing release mutex must belong to parent shell')
    try:
        if args.mode == 'inspect':
            state = job.load(allow_accepted_current=True)
            print(json.dumps({'phase': state['phase'], 'release': state['release'],
                              'current': str((job.app / 'current').resolve()), 'recovery_marker': job.marker.exists(),
                              'config_original': digest(private_bytes(job.env)) == state['original_hash'],
                              'config_paused': digest(private_bytes(job.env)) == state['paused_hash'],
                              'writers': {name: {'id': job.service(name)['Id'], 'running': job.service(name)['State']['Running']} for name in WRITERS}}))
        else:
            getattr(job, args.mode.replace('-', '_'))()
            print(json.dumps({'mode': args.mode, 'result': 'verified', 'release': str(job.release)}))
    finally:
        if owns_lock:
            (lock / 'pid').unlink(); lock.rmdir()


if __name__ == '__main__':
    try:
        main()
    except (Exception, CutoverInterrupted, KeyboardInterrupt):
        raise SystemExit('Dispatch cutover refused or failed; preserve marker/fence and inspect private journal; no retry or old producer start') from None
