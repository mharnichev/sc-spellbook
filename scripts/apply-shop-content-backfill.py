#!/usr/bin/env python3
"""Apply one reviewed content transaction; preserve original data and recovery fences."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys

TOOLS = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('content_release_safety', TOOLS/'activate-shop-online.py')
SAFE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAFE)
APP = Path('/opt/soulcuts')
HEAD = '0138_shop_content_en'
NAME = 'prod-public-dynamic-en.json'
INPUT_SHA = '992d43055f3266de376be3b85085078633c4b68c4c7412fba4681a155bd1110a'
COUNT = 228
FIELDS = ('description_en', 'short_description_en', 'ingredients_en')
SOURCE_FIELDS = ('description', 'short_description', 'ingredients')
TOOL_NAMES = ('apply-shop-content-backfill.py', 'shop-content-backfill-db.py',
              'english-backfill-db.py', 'english-backfill-network-guard.py',
              'run-shop-content-backfill.sh', 'activate-shop-online.py', 'shop-online-config.py')


def tool_hashes():
    for name in TOOL_NAMES:
        SAFE.require((TOOLS/name).is_file() and not (TOOLS/name).is_symlink())
    return {name: SAFE.sha((TOOLS/name).read_bytes()) for name in TOOL_NAMES}


def input_bytes(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        SAFE.require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                     and stat.S_IMODE(info.st_mode) == 0o400)
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            return stream.read()
    finally:
        os.close(fd)


def cleanup(prefix, *, stop=True):
    SAFE.require(re.fullmatch(r'english-content-[0-9a-f]{24}', prefix))
    args = ['docker', 'ps', '--format', '{{.ID}} {{.Names}}',
            '--filter', 'label=com.docker.compose.project=soulcuts',
            '--filter', 'label=com.docker.compose.service=migrate',
            '--filter', 'label=com.soulcuts.english-content-run='+prefix]
    found = SAFE.run(args, timeout=30)
    SAFE.require(stop or not found, 'A content database task is still running')
    for line in found.splitlines():
        identifier, name = line.split()
        SAFE.require(re.fullmatch(r'[0-9a-f]{12,64}', identifier)
                     and re.fullmatch(re.escape(prefix)+r'-[a-z-]+-[0-9a-f]{8}', name))
        SAFE.run(['docker', 'stop', '--time', '5', identifier], timeout=30)
    SAFE.require(not SAFE.run(args, timeout=30), 'Content task cleanup failed')


def cleanup_release(root):
    args = ['docker', 'ps', '--format', '{{.Names}}',
            '--filter', 'label=com.docker.compose.project=soulcuts',
            '--filter', 'label=com.docker.compose.service=migrate',
            '--filter', 'label=com.soulcuts.english-content-release='+str(root)]
    for name in SAFE.run(args, timeout=30).splitlines():
        match = re.fullmatch(r'(english-content-[0-9a-f]{24})-[a-z-]+-[0-9a-f]{8}', name)
        SAFE.require(match is not None)
        cleanup(match.group(1))
    SAFE.require(not SAFE.run(args, timeout=30), 'Content release tasks remain active')


def targets_from_report(payload, baseline, report):
    items = payload.get('products', [])
    SAFE.require(payload.get('count') == COUNT and payload.get('failures') == []
                 and len(items) == COUNT and all(type(row.get('id')) is int for row in items))
    inputs = {row['id']: row for row in items}
    records = report.get('records', [])
    SAFE.require(len(inputs) == COUNT and len(records) == COUNT
                 and all(type(row.get('id')) is int for row in records)
                 and len({row['id'] for row in records}) == COUNT
                 and {row['id'] for row in records} == set(inputs))
    catalog = {row['id']: row for row in baseline['catalog']['products']}
    target = copy.deepcopy(baseline['english'])
    SAFE.require(set(target) == {'products'})
    vector = {row['id']: row for row in target['products']}
    for row in records:
        identifier = row['id']
        SAFE.require(identifier in catalog and identifier in vector)
        SAFE.require(row['slug'] == inputs[identifier]['slug'] == catalog[identifier]['slug'])
        SAFE.require(row['source_raw'] == {key: catalog[identifier][key] for key in SOURCE_FIELDS}
                     and row['source_public'] == inputs[identifier]['source'])
        previous = {key: vector[identifier][key] for key in FIELDS}
        SAFE.require(row['previous'] == previous and set(row['desired']) == set(FIELDS))
        SAFE.require(all(previous[key] is None or previous[key] == row['desired'][key] for key in FIELDS),
                     'Existing manual content differs')
        vector[identifier].update(row['desired'])
    return target


def main():
    os.umask(0o077)
    SAFE.require(not sys.flags.optimize and len(sys.argv) >= 3)
    mode = sys.argv[1]
    SAFE.require(mode in ('apply', 'reconcile', 'rollback', 'recover-finalize', 'finalize'))
    SAFE.require(len(sys.argv) == (4 if mode == 'apply' else 3))
    root, pin = SAFE.release_context()
    SAFE.require(TOOLS == root.resolve()/'scripts')
    env = APP/'env/backend.env'
    marker = APP/'english-backfill-required'
    SAFE.writers(mode == 'finalize', pin)
    if mode == 'apply':
        SAFE.require(not marker.exists() and not marker.is_symlink())
        source = Path(sys.argv[2])
        SAFE.require(source.parent == APP/'backups' and not source.is_symlink())
        SAFE.private(source, 0o700, directory=True)
        raw = SAFE.read_private(source/NAME)
        SAFE.require(sys.argv[3] == INPUT_SHA and SAFE.sha(raw) == INPUT_SHA, 'Unreviewed content input')
        report = APP/'backups'/('english-content-'+secrets.token_hex(12))
        report.mkdir(mode=0o700)
        SAFE.sync_dir(report.parent)
        inputs, reports = report/'reviewed-inputs', report/'reports'
        inputs.mkdir(mode=0o700)
        reports.mkdir(mode=0o700)
        SAFE.sync_dir(report)
        SAFE.persist_bytes(inputs/NAME, raw)
        (inputs/NAME).chmod(0o400)
        fd = os.open(inputs/NAME, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        SAFE.sync_dir(inputs)
        state = dict(version=1, release=str(root), image=pin, head=HEAD, run=str(report),
                     env_sha256=SAFE.sha(SAFE.read_private(env)), input_sha256=INPUT_SHA,
                     tools=tool_hashes(), pre_restart_original_verified=False, phase='planning')
        print(json.dumps({'private_reports': str(report), 'production_updates_started': False}), flush=True)
    else:
        report = Path(sys.argv[2])
        SAFE.require(report.parent == APP/'backups' and re.fullmatch(r'english-content-[0-9a-f]{24}', report.name))
        SAFE.private(report, 0o700, directory=True)
        if marker.exists() or marker.is_symlink():
            state = SAFE.json_private(marker)
        else:
            SAFE.require(mode in ('finalize', 'recover-finalize', 'rollback'))
            receipt = SAFE.json_private(report/('rolled-back.json' if mode == 'rollback' else 'finalized.json'))
            SAFE.require(receipt.get('restored' if mode == 'rollback' else 'accepted') is True)
            state = receipt['state']
        SAFE.require(state['release'] == str(root) and state['image'] == pin
                     and state['head'] == HEAD and state['run'] == str(report)
                     and state['input_sha256'] == INPUT_SHA and state['tools'] == tool_hashes())
        inputs, reports = report/'reviewed-inputs', report/'reports'
        cleanup(report.name, stop=mode != 'finalize')

    def binding():
        SAFE.require(SAFE.sha(SAFE.read_private(env)) == state['env_sha256']
                     and SAFE.sha(input_bytes(inputs/NAME)) == INPUT_SHA
                     and tool_hashes() == state['tools'], 'Content release provenance changed')

    def save(phase):
        state['phase'] = phase
        SAFE.persist(marker, state, replace=marker.exists())

    def task(step, command, payload=None):
        binding()
        if marker.exists():
            save('executing-'+step)
        name = report.name+'-'+step+'-'+secrets.token_hex(4)
        args = ['docker', 'run', '--rm', '-i', '--pull=never', '--name', name,
                '--label', 'com.docker.compose.project=soulcuts',
                '--label', 'com.docker.compose.service=migrate',
                '--label', 'com.soulcuts.english-content-run='+report.name,
                '--label', 'com.soulcuts.english-content-release='+str(root),
                '--network', 'container:'+SAFE.cid('postgres'), '--memory=768m', '--cpus=1', '--pids-limit=128',
                '--user', f'{os.geteuid()}:{os.getegid()}',
                '--env-file', str(APP/'env/postgres.env'), '--env-file', str(env),
                '-e', 'POSTGRES_HOST=postgres', '-e', 'POSTGRES_PORT=5432',
                '-e', 'APP_ENV=production', '-e', 'DEBUG=false', '-e', 'BACKGROUND_WORKERS_ENABLED=false',
                '-v', str(root)+':/release-tools:ro', '-v', str(inputs)+':/reviewed-inputs:ro',
                '-v', str(reports)+':/english-reports:rw', '--entrypoint', 'python', pin,
                '/release-tools/scripts/english-backfill-network-guard.py', *command]
        value = json.loads(SAFE.run(args, data=None if payload is None else json.dumps(payload)))
        binding()
        return value

    def db(step, operation, payload=None):
        return task(step, ['/release-tools/scripts/shop-content-backfill-db.py', operation], payload)

    def cli(phase, expected_updates):
        filename = 'content-'+phase+'.json'
        command = ['-m', 'app.utils.backfill_shop_content_en', '--input', '/reviewed-inputs/'+NAME,
                   '--report', '/english-reports/'+filename]
        if phase == 'apply':
            command.append('--apply')
        result = task(phase, command)
        data = SAFE.json_private(reports/filename)
        SAFE.require(result.get('status') == ('committed' if phase == 'apply' else 'dry_run')
                     and result.get('count') == COUNT and result.get('updated') == expected_updates)
        SAFE.require(data.get('status') == ('prepared_apply' if phase == 'apply' else 'dry_run')
                     and data.get('input_sha256') == INPUT_SHA and data.get('count') == COUNT)
        return result, data

    try:
        binding()
        if mode == 'apply':
            baseline = db('snapshot', 'snapshot')
            SAFE.require(baseline['head'] == HEAD)
            # The approved CLI supplies canonical HTML and validates all reviewed source CAS values.
            command = ['-m', 'app.utils.backfill_shop_content_en', '--input', '/reviewed-inputs/'+NAME,
                       '--report', '/english-reports/content-dry-run.json']
            dry = task('dry-run', command)
            dry_report = SAFE.json_private(reports/'content-dry-run.json')
            SAFE.require(dry.get('status') == 'dry_run' and dry.get('count') == COUNT
                         and dry_report.get('status') == 'dry_run'
                         and dry_report.get('input_sha256') == INPUT_SHA and dry_report.get('count') == COUNT)
            target = targets_from_report(json.loads(input_bytes(inputs/NAME)), baseline, dry_report)
            planned = sum(old != new for old, new in zip(baseline['english']['products'], target['products']))
            SAFE.require(dry.get('updated') == planned)
            payload = dict(baseline=baseline, target=target)
            SAFE.persist(report/'snapshot.json', payload)
            state['snapshot_sha256'] = SAFE.sha(SAFE.read_private(report/'snapshot.json'))
            binding()
            save('prepared')
            result, _ = cli('apply', planned)
            cli('idempotent', 0)
            SAFE.require(db('verify-original', 'verify', payload).get('verified') is True)
            state['pre_restart_original_verified'] = True
            save('verified')
            print(json.dumps({'applied': True, 'result': result, 'reports': str(report),
                              'recovery_marker_retained': True, 'services_started': False}))
            return
        snapshot = SAFE.read_private(report/'snapshot.json')
        SAFE.require(SAFE.sha(snapshot) == state['snapshot_sha256'])
        payload = json.loads(snapshot)
        if mode == 'rollback':
            SAFE.require(db('rollback', 'rollback', payload).get('rolled_back') is True)
            state['phase'] = 'rolled-back'
            receipt_path, receipt = report/'rolled-back.json', {'restored': True, 'state': state}
        elif mode == 'reconcile':
            data = SAFE.json_private(reports/'content-apply.json')
            SAFE.require(data.get('status') == 'prepared_apply' and data.get('input_sha256') == INPUT_SHA)
            SAFE.require(db('reconcile', 'verify', payload).get('verified') is True)
            state['pre_restart_original_verified'] = True
            save('verified')
            print(json.dumps({'reconciled': True, 'recovery_marker_retained': True}))
            return
        else:
            SAFE.require(state.get('pre_restart_original_verified') is True)
            if mode == 'finalize':
                SAFE.require(os.environ.get('ENGLISH_RUNTIME_VERIFIED') == 'true')
            SAFE.require(db('verify-live', 'verify-live', payload).get('verified') is True)
            if mode == 'recover-finalize':
                if marker.exists():
                    save('verified')
                print(json.dumps({'finalization_reconciled': True, 'english_marker': marker.exists()}))
                return
            state['phase'] = 'verified'
            receipt_path, receipt = report/'finalized.json', {'accepted': True, 'state': state}
        binding()
        if receipt_path.exists() or receipt_path.is_symlink():
            SAFE.require(SAFE.json_private(receipt_path) == receipt)
            SAFE.resync(receipt_path)
        else:
            SAFE.persist(receipt_path, receipt)
        if marker.exists():
            marker.unlink()
            SAFE.sync_dir(APP)
        print(json.dumps({'operation': mode, 'verified': True, 'backend_fence_retained': True}))
    finally:
        cleanup(report.name)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Content backfill failed closed; inspect private state and retain backend fence') from None
