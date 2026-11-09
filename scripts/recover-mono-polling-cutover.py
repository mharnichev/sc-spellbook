#!/usr/bin/env python3
"""Version 1, exact-release recovery. No original journal or release file writes.

Execution needs the independently reviewed binding.json. Tests use fake boundaries.
Never logs response_json, intent scope keys, provider URLs or environment bytes.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import threading
import time
import uuid

VERSION = 1
APP = Path('/opt/soulcuts')
RELEASE = APP / 'releases/20261109T191645Z-4044a8c'
BACKUP = APP / 'backups/pilot-WLyzSOrK'
HELPER_SHA = '003fea1cd83814dcf75c04ce2b0392a0852ad7a87d2c496409ea41986d56449e'
PINS_SHA = 'ceefa7a8dbca77cdbcd65db987e7a6348aea26c9d4951d56913e31e12321699d'
ORIGINAL_JOURNAL_SHA = '23e47db3c49bb12f1985886a82fff04ba941d17b4776160d63dde5031b99ff65'
MANIFEST_SHA = '4b926b3b0c5637bfe84ae93f6191250711844b6765fb991a4c79719cd5720ddd'
PG_IMAGE = 'postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea'
BASELINE_INTENTS = '5c3949eb723302e8fa82275f2d80420e'
HEAD = '0151_master_mono_url_provenance'
KEYS = {'enabled', 'order_id', 'revision', 'mode', 'paid', 'receipt_accepted', 'status',
        'amount_minor', 'invoice_id', 'payment_url', 'payment_url_source',
        'payment_url_expires_at', 'receipt_pdf_path', 'can_handover',
        'can_verify_invoice', 'blocking_reasons'}
PROTECTED = ('requests', 'unresolved', 'protected', 'closures', 'closure_orders', 'conflicts')
FINANCIAL_TABLES = ('master_mono_bindings', 'master_mono_payments', 'master_mono_receipts',
 'master_mono_artifacts', 'master_mono_create_requests', 'master_mono_create_candidates',
 'master_mono_candidate_expiries', 'master_mono_candidate_conflicts', 'master_mono_expired_closures',
 'master_mono_closed_conflicts', 'order_payments', 'fiscal_documents', 'order_handovers',
 'inventory_movements', 'order_items', 'pos_checkout_intents')
INTENTS_SQL = """SELECT coalesce(json_agg(x ORDER BY scope_key),'[]') FROM
(SELECT scope_key,payload_hash,order_id,response_json,
 md5(to_jsonb(i)::text) row_hash FROM order_intents i) x;"""


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def aggregate(rows):
    return hashlib.md5(''.join(sorted(row['row_hash'] for row in rows)).encode()).hexdigest()


def response(value):
    require(type(value) is dict and set(value) == KEYS, 'Unexpected MasterMonoState keys')
    for key in ('enabled', 'paid', 'receipt_accepted', 'can_handover', 'can_verify_invoice'):
        require(type(value[key]) is bool, 'Unexpected boolean type')
    for key in ('order_id', 'revision', 'amount_minor'):
        require(type(value[key]) is int and value[key] > 0, 'Unexpected integer type')
    require(value['order_id'] == 7 and value['mode'] == 'mono_checkbox'
            and value['status'] == 'mono_checkbox_receipt_pending' and value['paid'] is True
            and value['receipt_accepted'] is False and value['can_handover'] is False,
            'Not an allowed pending paid order7 snapshot')
    for key in ('mode', 'status'):
        require(type(value[key]) is str, 'Unexpected string type')
    for key in ('invoice_id', 'payment_url', 'payment_url_source', 'payment_url_expires_at', 'receipt_pdf_path'):
        require(value[key] is None or type(value[key]) is str, 'Unexpected optional string type')
    require(type(value['blocking_reasons']) is list
            and all(type(item) is str for item in value['blocking_reasons']), 'Unexpected blocking reasons')
    return {key: item for key, item in value.items() if key != 'revision'}


def keyed(rows):
    require(type(rows) is list, 'Intent rows unavailable')
    result = {}
    for row in rows:
        require(type(row) is dict and set(row) == {'scope_key', 'payload_hash', 'order_id', 'response_json', 'row_hash'},
                'Unexpected intent row shape')
        key = row['scope_key']
        require(type(key) is str and re.fullmatch('[0-9a-f]{64}', key)
                and key not in result and re.fullmatch('[0-9a-f]{32}', row['row_hash']), 'Invalid or duplicate intent key/hash')
        result[key] = row
    return result


def prove_append_only(baseline, current, baseline_hash=BASELINE_INTENTS):
    """Full trusted dump rows; validate append content before freezing a finite union."""
    before, after = keyed(baseline), keyed(current)
    require(len(before) == 352 and aggregate(baseline) == baseline_hash, 'Paired dump does not prove original 352-row baseline')
    require(before.keys() <= after.keys(), 'Baseline intent deleted')
    require(all(before[key] == after[key] for key in before), 'Baseline intent mutated')
    pending = [row for row in baseline if row['order_id'] == 7
               and type(row['response_json']) is dict
               and row['response_json'].get('status') == 'mono_checkbox_receipt_pending'
               and row['response_json'].get('paid') is True
               and row['response_json'].get('receipt_accepted') is False]
    require(pending, 'Trusted pending order7 template missing')
    template_row = max(pending, key=lambda row: row['response_json']['revision'])
    template = response(template_row['response_json'])
    base_revision = template_row['response_json']['revision']
    require(base_revision == 337, 'Unexpected trusted order7 baseline revision')
    added = [after[key] for key in after.keys() - before.keys()]
    require(0 < len(added) <= 4096, 'Unexpected finite append-set size')
    revisions = []
    for row in added:
        require(type(row['order_id']) is int and row['order_id'] == 7, 'Added intent outside order7')
        value = row['response_json']
        require(response(value) == template, 'Added response differs from trusted full template')
        revision = value['revision']
        expected = sha(json.dumps({'expected_revision': revision - 1}, sort_keys=True, separators=(',', ':')).encode())
        require(row['payload_hash'] == expected, 'Refresh payload hash differs')
        revisions.append(revision)
    require(sorted(revisions) == list(range(base_revision + 1, base_revision + len(added) + 1)),
            'Added revisions are not contiguous')
    return {'rows': {key: row['row_hash'] for key, row in after.items()},
            'prepared_intents': aggregate(current), 'added_count': len(added),
            'first_revision': base_revision + 1, 'last_revision': max(revisions)}


def verify_frozen(proof, rows):
    actual = keyed(rows)
    require({key: row['row_hash'] for key, row in actual.items()} == proof['rows']
            and aggregate(rows) == proof['prepared_intents'], 'Frozen intent union changed')


def verify_binding(binding, actual):
    expected = {'version': VERSION, 'release': str(RELEASE), 'helper_sha256': HELPER_SHA,
                'pins_sha256': PINS_SHA, 'manifest_sha256': MANIFEST_SHA,
                'original_journal_sha256': ORIGINAL_JOURNAL_SHA}
    require(binding == expected, 'Exact reviewed binding differs')
    require(actual == {key: value for key, value in expected.items() if key.endswith('_sha256')},
            'Exact source, pins, journal or manifest hash differs')


def load_helper():
    path = RELEASE / 'scripts/master-mono-dispatch-cutover.py'
    require(sha(path.read_bytes()) == HELPER_SHA, 'Original helper source hash changed')
    spec = importlib.util.spec_from_file_location('original_cutover_v1', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Lease:
    """Dedicated psql session; round-trip checks prove the SAME backend still owns lock.

    The guardian owns stdin. EOF on guardian death closes this read-only transaction.
    A worker also monitors guardian death; the guardian fences on worker/lease failure.
    """
    def __init__(self, command, deadline):
        self.deadline = deadline
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0, close_fds=True)
        self.buffer = b''
        self.backend = None
        try:
            self.exchange("BEGIN READ ONLY; SET LOCAL statement_timeout='60s'; SELECT pg_advisory_lock(1396919372,13);")
            self.check()
        except BaseException:
            self.close()
            raise

    def exchange(self, sql):
        require(time.monotonic() < self.deadline and self.process.poll() is None, 'Polling lease deadline/process lost')
        token = 'lease_' + uuid.uuid4().hex
        self.process.stdin.write((sql + "\n\\echo " + token + '\n').encode())
        self.process.stdin.flush()
        end = min(self.deadline, time.monotonic() + 65)
        while time.monotonic() < end:
            ready, _, _ = select.select([self.process.stdout], [], [], min(0.5, end - time.monotonic()))
            require(self.process.poll() is None, 'Polling lease process exited')
            if ready:
                chunk = os.read(self.process.stdout.fileno(), 4096)
                require(chunk, 'Polling lease stream closed')
                self.buffer += chunk
                marker = (token + '\n').encode()
                if marker in self.buffer:
                    value, self.buffer = self.buffer.split(marker, 1)
                    return value.decode().strip()
        raise RuntimeError('Polling lease response deadline exceeded')

    def check(self):
        result = self.exchange("SELECT pg_backend_pid()::text||':'||count(*)::text FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory' AND classid=1396919372 AND objid=13 AND objsubid=2 AND granted;")
        parts = result.split(':')
        require(len(parts) == 2 and parts[0].isdigit() and parts[1] == '1', 'Scheduler advisory lock no longer held')
        require(self.backend is None or self.backend == parts[0], 'Lease backend identity changed')
        self.backend = parts[0]

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.stdin.close()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    self.process.wait(timeout=5)
        finally:
            self.process.stdin.close()
            self.process.stdout.close()


def make_controller(module):
    class Controller(module.Cutover):
        def __init__(self, binding, check_lease=lambda: None):
            super().__init__(RELEASE, APP)
            self.binding = binding
            self.guardian_pid = os.getpid()
            self.stage = 'preflight'
            self.check_lease = check_lease
            self.sidecar_dir = APP / 'backups/polling-recovery-v1-20261109T191645Z-4044a8c'
            self.sidecar = self.sidecar_dir / 'journal.json'
            self.original_journal = self.journal
            self.original_raw = module.private_bytes(self.original_journal)
            verify_binding(binding, {
                'helper_sha256': sha((RELEASE / 'scripts/master-mono-dispatch-cutover.py').read_bytes()),
                'pins_sha256': sha((RELEASE / 'versions/production.env').read_bytes()),
                'manifest_sha256': sha(module.private_bytes(BACKUP / 'manifest.json')),
                'original_journal_sha256': sha(self.original_raw)})
            self.initial = json.loads(self.original_raw)
            require(self.initial['phase'] == 'paused_verified'
                    and self.initial['baseline']['head'] == HEAD
                    and self.initial['baseline']['compatibility']['prepared_intents'] == BASELINE_INTENTS,
                    'Original cutover checkpoint differs')
            self.verify_original()

        def verify_original(self):
            require(not self.directory.is_symlink() and self.directory.stat().st_uid == os.geteuid()
                    and module.stat.S_IMODE(self.directory.stat().st_mode) == 0o700, 'Private original cutover directory required')
            require(module.private_bytes(self.original_journal) == self.original_raw, 'Original journal changed')
            require(sha((RELEASE / 'scripts/master-mono-dispatch-cutover.py').read_bytes()) == HELPER_SHA,
                    'Original helper changed')
            require(sha((RELEASE / 'versions/production.env').read_bytes()) == PINS_SHA, 'Release pins changed')
            require(sha(module.private_bytes(BACKUP / 'manifest.json')) == MANIFEST_SHA, 'Paired manifest changed')
            if self.marker.exists():
                require(self.marker_matches().get('backup') == str(BACKUP), 'Exact paired backup marker differs')
            else:
                require(self.sidecar.exists() and json.loads(module.private_bytes(self.sidecar))['phase'] == 'complete'
                        and (APP / 'current').resolve() == RELEASE, 'Original recovery marker missing')
            manifest = json.loads(module.private_bytes(BACKUP / 'manifest.json'))
            require(set(manifest) == {'soulcuts-postgres-20261109T191706Z.dump', 'soulcuts-files-20261109T191709Z.tar.gz'},
                    'Exact paired archive names differ')
            require(not BACKUP.is_symlink() and BACKUP.stat().st_mode & 0o077 == 0, 'Private paired backup required')
            for name, expected in manifest.items():
                data = module.private_bytes(BACKUP / name)
                require(len(data) == expected['bytes'] > 0 and sha(data) == expected['sha256'], 'Paired archive checksum differs')

        def sql(self, query, container=None):
            if container:
                command = ['docker', 'exec', '-i', container, 'psql', '-X', '-q', '-At', '-v', 'ON_ERROR_STOP=1',
                           '-U', 'rehearsal', '-d', 'restore_copy']
            else:
                command = self.psql_command()
            return self.run(command, ('BEGIN READ ONLY; SET LOCAL statement_timeout=\'8s\';\n' + query + '\nROLLBACK;').encode()).decode().strip()

        def psql_command(self):
            return ['docker', 'exec', '-i', self.service('postgres')['Id'], 'sh', '-ec',
                    'exec psql -X -q -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"']

        def intents(self, container=None):
            return json.loads(self.sql(INTENTS_SQL, container))

        def financial(self, container=None):
            output = {}
            for table in FINANCIAL_TABLES:
                output[table] = self.sql("SELECT md5(coalesce(string_agg(row_to_json(t)::text,E'\\n' ORDER BY row_to_json(t)::text),'')) FROM " + table + ' t;', container)
            for label, query in {
                'stock': 'SELECT id,stock_quantity,reserved_quantity FROM products',
                'sales': "SELECT to_jsonb(o)-'revision'-'updated_at' AS immutable_order FROM orders o"
            }.items():
                output[label] = self.sql("SELECT md5(coalesce(string_agg(row_to_json(t)::text,E'\\n' ORDER BY row_to_json(t)::text),'')) FROM (" + query + ') t;', container)
            return output

        def checkpoint(self):
            require(int((APP / 'release.lock/pid').read_text()) == self.guardian_pid, 'Release mutex owner changed')
            self.check_lease()
            self.verify_original()

        def restore_proof(self):
            self.stage = 'restore_paired_backup'
            self.checkpoint()
            name = 'ready-ui-recovery-v1-' + uuid.uuid4().hex[:12]
            network = name + '-net'
            made_network = made_pg = False
            try:
                self.run(['docker', 'network', 'create', '--internal', network]); made_network = True
                self.run(['docker', 'run', '-d', '--pull=never', '--name', name, '--network', network,
                    '--memory=2g', '--cpus=1', '--pids-limit=256',
                    '--tmpfs', '/var/lib/postgresql/data:rw,size=1536m,mode=0700',
                    '-e', 'PGDATA=/var/lib/postgresql/data', '-e', 'POSTGRES_USER=rehearsal',
                    '-e', 'POSTGRES_DB=restore_copy', '-e', 'POSTGRES_INITDB_ARGS=--locale=en_US.utf8',
                    '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', PG_IMAGE]); made_pg = True
                self.run(['docker', 'exec', name, 'sh', '-ec',
                    'for i in $(seq 1 60); do pg_isready -U rehearsal -d restore_copy && exit 0; sleep 1; done; exit 1'])
                dump, = BACKUP.glob('*.dump')
                with dump.open('rb') as stream:
                    result = subprocess.run(['docker', 'exec', '-i', name, 'pg_restore', '--exit-on-error',
                        '--single-transaction', '--no-owner', '--no-privileges', '-U', 'rehearsal', '-d', 'restore_copy'],
                        stdin=stream, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
                require(result.returncode == 0, 'Isolated paired restore failed')
                require(self.sql('SELECT version_num FROM alembic_version;', name) == HEAD, 'Restored schema differs')
                baseline = self.intents(name)
                financial = self.financial(name)
                self.checkpoint()
                self.stage = 'prove_financial_facts'
                require(self.financial() == financial, 'Financial facts or stock changed from exact paired backup')
                self.stage = 'prove_finite_intent_append'
                proof = prove_append_only(baseline, self.intents())
                self.checkpoint()
                verify_frozen(proof, self.intents())
                return proof, financial
            finally:
                try:
                    if made_pg:
                        self.run(['docker', 'rm', '-f', name])
                finally:
                    if made_network:
                        self.run(['docker', 'network', 'rm', network])

        def prepare_sidecar(self):
            require(not self.sidecar_dir.exists(), 'Sidecar exists; inspect and refence, no automatic retry')
            self.sidecar_dir.mkdir(mode=0o700)
            module.sync_directory(self.sidecar_dir.parent)
            state = copy.deepcopy(self.initial)
            state['controller_version'] = VERSION
            state['binding'] = self.binding
            # Literal copy: all original baseline fields stay unchanged.
            module.persist(self.sidecar, state, exclusive=True)
            proof, financial = self.restore_proof()
            self.frozen_proof = copy.deepcopy(proof)
            self.paired_financial = copy.deepcopy(financial)
            state['finite_intent_proof'] = proof
            state['paired_financial'] = financial
            self.save(state, 'paused_verified')
            return state

        def load(self, allow_accepted_current=False):
            self.checkpoint()
            require(not self.sidecar_dir.is_symlink() and self.sidecar_dir.stat().st_uid == os.geteuid()
                    and module.stat.S_IMODE(self.sidecar_dir.stat().st_mode) == 0o700, 'Private sidecar directory required')
            state = json.loads(module.private_bytes(self.sidecar))
            require(state['controller_version'] == VERSION and state['binding'] == self.binding
                    and all(state.get(key) == value for key, value in self.initial.items() if key != 'phase'),
                    'Sidecar binding or original checkpoint changed')
            current = str((APP / 'current').resolve(strict=True))
            if current != state['previous']:
                require(allow_accepted_current and current == str(RELEASE) and state.get('acceptance_started') is True
                        and state['phase'] in ('accepting', 'accepted', 'switched', 'recovery_required'),
                        'Current changed outside exact acceptance transition')
            return state

        def save(self, state, phase):
            require(state['baseline'] == self.initial['baseline'], 'No baseline rewrite permitted')
            state['phase'] = phase
            module.persist(self.sidecar, state)

        def verify_live(self, state, paused, previous_ids):
            self.stage = 'verify_exact_live_pair'
            self.checkpoint()
            require(state['finite_intent_proof'] == self.frozen_proof
                    and state['paired_financial'] == self.paired_financial, 'Frozen proof changed')
            require(self.marker_matches().get('phase') == 'pending_acceptance', 'Pending acceptance required')
            original = self.original(state)
            require(module.private_bytes(self.env) == (module.paused_env(original) if paused else original), 'Config differs from phase')
            self.run(['python3', str(RELEASE / 'scripts/verify-deployed-images.py')])
            self.run(['bash', str(RELEASE / 'scripts/verify-background-owner.sh')])
            ids = {}
            for name in module.WRITERS:
                info = self.service(name)
                require(info['Id'] != previous_ids[name] and info['State']['Running']
                        and (name != 'backend' or (info['State'].get('Health') or {}).get('Status') == 'healthy'),
                        'New healthy writer identity required')
                module.verify_flags(state['flags'][name], self.flags(info), paused)
                ids[name] = info['Id']
            after = self.snapshot()
            require(after['head'] == HEAD, 'Exact target0151 required')
            for key in PROTECTED:
                require(after[key] == state['baseline'][key], 'Protected dispatch history changed: ' + key)
            expected = {**state['baseline']['compatibility'],
                        'prepared_intents': state['finite_intent_proof']['prepared_intents']}
            require(after['compatibility'] == expected, 'Exact finite intent union or binding changed')
            verify_frozen(state['finite_intent_proof'], self.intents())
            require(self.financial() == state['paired_financial'], 'Paired financial facts or stock changed')
            self.checkpoint()
            return ids

        def resume_accept(self):
            self.stage = 'resume_admission'
            state = self.load()
            require(state['phase'] == 'paused_verified', 'Resume requires verified paused pair')
            require(os.environ.get('PILOT_MANUAL_GATE') == 'verified' and os.environ.get('EXPECTED_RELEASE') == str(RELEASE),
                    'Exact reviewed manual paired gates required')
            ids = self.verify_live(state, True, {name: state['writers'][name]['id'] for name in module.WRITERS})
            require(ids == state['paused_ids'], 'Paused writers changed since original verification')
            self.save(state, 'resume_intent')
            try:
                self.checkpoint()
                original = self.original(state)
                self.stage = 'enable_config'
                module.cas_env(self.env, module.paused_env(original), original)
                self.checkpoint()
                self.stage = 'recreate_writers'
                self.start_writers()
                state['resumed_ids'] = self.verify_live(state, False, state['paused_ids'])
                self.save(state, 'resumed')
                for marker in ('master-qr-activation-required', 'english-backfill-required', 'shop-online-activation-required'):
                    path = APP / marker
                    require(not path.exists() and not path.is_symlink(), 'Other activation recovery required')
                ids = self.verify_live(state, False, {name: state['writers'][name]['id'] for name in module.WRITERS})
                require(ids == state['resumed_ids'], 'Resumed writers replaced')
                state['acceptance_started'] = True
                self.save(state, 'accepting')
                self.checkpoint()
                self.stage = 'switch_current'
                temporary = APP / ('polling-current-v1-' + uuid.uuid4().hex)
                require((APP / 'current').is_symlink()
                        and str((APP / 'current').resolve()) == state['previous'], 'Current pointer drifted')
                try:
                    temporary.symlink_to(RELEASE)
                    os.replace(temporary, APP / 'current')
                    module.sync_directory(APP)
                finally:
                    if temporary.is_symlink(): temporary.unlink()
                self.save(state, 'accepted')
                state = self.load(allow_accepted_current=True)
                require((APP / 'current').resolve() == RELEASE and state['phase'] == 'accepted', 'Exact accepted current required')
                self.verify_live(state, False, {name: state['writers'][name]['id'] for name in module.WRITERS})
                self.save(state, 'switched')
                self.checkpoint()
                self.stage = 'remove_marker'
                self.marker.unlink()
                module.sync_directory(APP)
                self.stage = 'complete_journal'
                self.save(state, 'complete')
                return state
            except BaseException:
                self.emergency_fence(state)
                raise

        def record_failure(self, error):
            if self.sidecar_dir.exists() and not (self.sidecar_dir / 'failure.json').exists():
                stage = getattr(self, 'stage', 'preflight')
                module.persist(self.sidecar_dir / 'failure.json', {
                    'stage': stage, 'reason_code': stage + '_failed',
                    'exception_class': type(error).__name__})

        def emergency_fence(self, state=None):
            # Independent of lease/pins validation: stop always precedes config restore.
            # Never call original save/load (original journal is immutable).
            previous = {number: signal.signal(number, signal.SIG_IGN)
                        for number in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)}
            error = None
            try:
                try:
                    self.run(self.compose + ['stop', '--timeout', '90', *module.WRITERS])
                except BaseException as caught:
                    error = caught
                try:
                    original = self.original(self.initial)
                    actual = module.private_bytes(self.env)
                    if actual == original:
                        module.cas_env(self.env, original, module.paused_env(original))
                    else:
                        require(actual == module.paused_env(original), 'Config drift; no emergency overwrite')
                except BaseException as caught:
                    error = error or caught
                try:
                    if not self.marker.exists():
                        fd = os.open(self.marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                        with os.fdopen(fd, 'wb') as stream:
                            stream.write(('release=' + str(RELEASE) + '\nbackup=' + str(BACKUP) + '\nphase=pending_acceptance\n').encode())
                            stream.flush(); os.fsync(stream.fileno())
                        module.sync_directory(APP)
                except BaseException as caught:
                    error = error or caught
                try:
                    if self.sidecar.exists():
                        record = state if state is not None else json.loads(module.private_bytes(self.sidecar))
                        self.save(record, 'recovery_required')
                except BaseException as caught:
                    error = error or caught
                try:
                    require(all(not self.service(name)['State']['Running'] for name in module.WRITERS),
                            'Writer stop not verified; retain recovery mutex')
                except BaseException as caught:
                    error = error or caught
                if error:
                    raise error
            finally:
                for number, handler in previous.items(): signal.signal(number, handler)

    return Controller


class WorkerPulse:
    def __init__(self, read_fd, guardian_pid):
        self.read_fd = read_fd
        self.guardian_pid = guardian_pid
        self.last = time.monotonic()
        threading.Thread(target=self.watch, daemon=True).start()

    def watch(self):
        while True:
            ready, _, _ = select.select([self.read_fd], [], [], 8)
            if not ready or not os.read(self.read_fd, 4096):
                os.kill(os.getpid(), signal.SIGTERM)
                return
            self.last = time.monotonic()

    def check(self):
        require(os.getppid() == self.guardian_pid and time.monotonic() - self.last < 3,
                'Guardian or confirmed lease heartbeat lost')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inspect', 'prove', 'resume-accept'))
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--proof-sidecar', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    module = load_helper()
    binding = json.loads(module.private_bytes(args.binding))
    cls = make_controller(module)
    job = cls(binding)
    if args.proof_sidecar:
        require(args.mode == 'inspect' and args.proof_sidecar.parent == APP / 'backups'
                and args.proof_sidecar.name.startswith('polling-proof-v1-'), 'Exact own proof sidecar required')
        job.sidecar_dir = args.proof_sidecar
        job.sidecar = job.sidecar_dir / 'journal.json'
    if args.mode == 'inspect':
        info = {}
        if job.sidecar.exists():
            require(not job.sidecar_dir.is_symlink() and job.sidecar_dir.stat().st_uid == os.geteuid()
                    and module.stat.S_IMODE(job.sidecar_dir.stat().st_mode) == 0o700, 'Private sidecar required')
            state = json.loads(module.private_bytes(job.sidecar))
            require(state['binding'] == binding and all(state.get(key) == value for key, value in job.initial.items() if key != 'phase'),
                    'Sidecar source checkpoint differs')
            proof = state.get('finite_intent_proof', {})
            info = {'sidecar_phase': state['phase'], 'intent_proof': {key: proof.get(key) for key in
                    ('added_count', 'first_revision', 'last_revision', 'prepared_intents')}}
            failure = job.sidecar_dir / 'failure.json'
            if failure.exists(): info['failure'] = json.loads(module.private_bytes(failure))
        print(json.dumps({'version': VERSION, 'release': str(RELEASE), 'original_phase': job.initial['phase'],
                          'sidecar_exists': job.sidecar.exists(), 'execution': 'not_started', **info}))
        return
    require(os.environ.get('PILOT_MANUAL_GATE') == 'verified' and os.environ.get('EXPECTED_RELEASE') == str(RELEASE),
            'Exact reviewed manual paired gates required')
    read_only = args.mode == 'prove'
    if read_only:
        job.sidecar_dir = APP / 'backups' / ('polling-proof-v1-' + uuid.uuid4().hex)
        job.sidecar = job.sidecar_dir / 'journal.json'
    lock = APP / 'release.lock'
    lock.mkdir()
    (lock / 'pid').write_text(str(os.getpid()) + '\n')
    module.sync_directory(lock)
    lease = None
    child = None
    child_reaped = False
    success = False
    fenced = False
    read_fd, write_fd = os.pipe()
    try:
        module.install_signal_handlers()
        lease = Lease(job.psql_command(), time.monotonic() + 900)
        child = os.fork()
        if child == 0:
            os.setsid()
            os.close(write_fd)
            # Do not keep the guardian's psql input or output descriptors alive.
            os.close(lease.process.stdin.fileno()); os.close(lease.process.stdout.fileno())
            pulse = WorkerPulse(read_fd, job.guardian_pid)
            job.check_lease = pulse.check
            try:
                state = job.prepare_sidecar()
                if read_only:
                    ids = job.verify_live(state, True, {name: state['writers'][name]['id'] for name in module.WRITERS})
                    require(ids == state['paused_ids'], 'Paused identities drifted during proof')
                    job.save(state, 'proof_verified')
                else:
                    job.resume_accept()
                os._exit(0)
            except BaseException as error:
                try:
                    try: job.record_failure(error)
                    finally:
                        if not read_only: job.emergency_fence()
                finally: os._exit(1)
        os.close(read_fd)
        while True:
            lease.check()
            pid, status = os.waitpid(child, os.WNOHANG)
            if pid:
                child_reaped = True
                worker_ok = os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
                require(worker_ok, 'Recovery worker failed; refence required')
                break
            os.write(write_fd, b'.')
            time.sleep(1)
        # Worker has switched, reverified, removed marker, and durably completed.
        state = json.loads(module.private_bytes(job.sidecar))
        if read_only:
            require(state['phase'] == 'proof_verified' and job.marker.exists()
                    and str((APP / 'current').resolve()) == job.initial['previous']
                    and module.private_bytes(job.env) == module.paused_env(job.original(job.initial)),
                    'Read-only proof was not durable or release state changed')
        else:
            require(state['phase'] == 'complete' and (APP / 'current').resolve() == RELEASE
                    and not job.marker.exists(), 'Completion was not durable')
        lease.check()
        success = True
        print(json.dumps({'version': VERSION, 'release': str(RELEASE), 'result': 'proof_verified' if read_only else 'accepted', 'sidecar': str(job.sidecar)}))
    except BaseException as error:
        try:
            job.stage = 'guardian_lease_or_worker'
            try: job.record_failure(error)
            except BaseException: pass
            if child and not child_reaped:
                try: os.killpg(child, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    try: os.kill(child, signal.SIGTERM)
                    except ProcessLookupError: pass
                end = time.monotonic() + 240
                while time.monotonic() < end:
                    try:
                        pid, _ = os.waitpid(child, os.WNOHANG)
                        if pid: break
                    except ChildProcessError: break
                    time.sleep(0.5)
                else:
                    try: os.killpg(child, signal.SIGKILL)
                    except ProcessLookupError: pass
                    os.waitpid(child, 0)
        finally:
            if not read_only: job.emergency_fence()
            fenced = True
        raise
    finally:
        os.close(write_fd)
        try:
            if lease: lease.close()
        finally:
            if success or fenced:
                require(int((lock / 'pid').read_text()) == os.getpid(), 'Release mutex owner drift; retain lock')
                (lock / 'pid').unlink()
                lock.rmdir()


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print(json.dumps({'version': VERSION, 'reason_code': 'preflight_or_controller_refused',
                          'exception_class': type(error).__name__}), file=sys.stderr)
        raise SystemExit('Polling recovery refused or failed; inspect private sidecar; no retry or old producer start') from None
