#!/usr/bin/env python3
"""Release-locked English metadata backfill with explicit whole-vector recovery."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile

APP = Path('/opt/soulcuts')
ENV = APP/'env/backend.env'
MARKER = APP/'english-backfill-required'
HEAD = '0136_category_names_en'
FIELDS = {'products':('name_en','product_type_en'), 'categories':('name_en',)}


def require(value, message='English release safety condition failed'):
    if not value:
        raise RuntimeError(message)


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def persist(path, value, *, replace=False):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    if replace:
        fd, name = tempfile.mkstemp(prefix='.'+path.name+'-', dir=path.parent)
    else:
        fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        name = str(path)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(name, path)
        sync_dir(path.parent)
    finally:
        if replace and os.path.exists(name):
            os.unlink(name)


def private_json(path):
    require(not path.is_symlink() and path.is_file())
    require(path.stat().st_uid == os.geteuid() and stat.S_IMODE(path.stat().st_mode) == 0o600)
    return json.loads(path.read_text())


def run(args, *, data=None, env=None, timeout=120):
    result = subprocess.run(args, input=data, text=True, capture_output=True, env=env, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Controlled English release command failed; private output suppressed')
    return result.stdout.strip()


def cid(service):
    value = run(['docker','ps','-aq','--filter','label=com.docker.compose.project=soulcuts',
                 '--filter','label=com.docker.compose.service='+service])
    require(value and '\n' not in value)
    return value


def writers(running, pin):
    for service in ('backend','booking-sms-reminders'):
        container = cid(service)
        require(run(['docker','inspect','--format','{{.State.Running}}',container]) == str(running).lower())
        require(run(['docker','inspect','--format','{{.Config.Image}}',container]) == pin)


def quiesce(names, prefix, *, stop):
    for name in names:
        require(name.startswith(prefix+'-') and re.fullmatch(r'[a-z0-9-]+', name), 'Unexpected recovery task identity')
        command = ['docker','ps','-q','--filter','name=^/'+name+'$',
                   '--filter','label=com.docker.compose.project=soulcuts',
                   '--filter','label=com.docker.compose.service=migrate',
                   '--filter','label=com.soulcuts.english-run='+prefix]
        found = run(command, timeout=30)
        if found:
            require(stop and '\n' not in found, 'A previous release task is still running')
            run(['docker','stop','--time','5',found], timeout=30)
            require(not run(command, timeout=30), 'Release task cleanup failed')


def targets_from_inputs(inputs, baseline):
    target = {}
    for table, fields in FIELDS.items():
        name = 'prod-all-names-en.json' if table == 'products' else 'prod-all-category-names-en.json'
        rows = json.loads((inputs/name).read_bytes())[table]
        require(all(type(row['id']) is int for row in rows))
        rows = sorted(rows, key=lambda row:row['id'])
        original = baseline['catalog'][table]
        require(len(rows) == (552 if table == 'products' else 44))
        require([row['id'] for row in rows] == [row['id'] for row in original])
        for row, old in zip(rows, original):
            require(row['name_original'] == old['name'] and row['slug'] == old['slug'], 'Catalog source changed')
            if table == 'categories':
                require(row['parent_id'] == old['parent_id'], 'Category hierarchy changed')
        target[table] = [{'id':row['id'], **{field:row[field] for field in fields}} for row in rows]
        for old, new in zip(baseline['english'][table], target[table]):
            require(all(old[field] is None or old[field] == new[field] for field in fields),
                    'Existing manual English translation differs')
    return target


def planned_updates(baseline, target, table):
    return sum(old != new for old, new in zip(baseline['english'][table], target[table]))


def main():
    require(not sys.flags.optimize, 'Optimized execution is forbidden')
    os.umask(0o077)
    mode = sys.argv[1]
    require(mode in ('apply','rollback','reconcile','recover-finalize','finalize'))
    owner = int((APP/'release.lock/pid').read_text().strip())
    require(owner == os.getppid() == int(os.environ.get('RELEASE_LOCK_OWNER_PID','-1')), 'Owning release wrapper required')
    os.kill(owner, 0)
    root = Path(os.environ['EXPECTED_RELEASE'])
    require(root.is_dir() and root.resolve().parent == (APP/'releases').resolve())
    backend = dict(line.split('=',1) for line in (APP/'backend-recovery-required').read_text().splitlines())
    require(backend.get('phase') == 'pending_acceptance' and backend.get('release') == str(root))
    require(not ENV.is_symlink() and ENV.stat().st_uid == os.geteuid() and stat.S_IMODE(ENV.stat().st_mode) == 0o600)
    pin = run(['python3',str(root/'scripts/release-backend-pin.py'),str(root/'versions/production.env')])
    require(pin == os.environ.get('EXPECTED_BACKEND_IMAGE') and re.fullmatch(r'ghcr\.io/mharnichev/sc-be/api@sha256:[0-9a-f]{64}',pin))
    process_env = dict(os.environ, BACKEND_IMAGE=pin, BACKEND_ENV_FILE=str(ENV), POSTGRES_ENV_FILE=str(APP/'env/postgres.env'))
    writers(mode == 'finalize', pin)
    tasks = []
    if mode == 'apply':
        require(not MARKER.exists() and not MARKER.is_symlink(), 'English recovery is already required')
        require(len(sys.argv) == 5)
        hashes = dict(products=sys.argv[3], categories=sys.argv[4])
        require(all(re.fullmatch(r'[0-9a-f]{64}', value) for value in hashes.values()))
        report_root = APP/'backups'/('english-catalog-'+secrets.token_hex(12))
        report_root.mkdir(mode=0o700)
        sync_dir(report_root.parent)
        spec = importlib.util.spec_from_file_location('english_rehearsal', root/'scripts/rehearse-shop-production-copy.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        inputs, hashes = module.seal_english_inputs(
            Path(sys.argv[2]), hashes, report_root, backup_root=APP/'backups')
        reports = report_root/'reports'
        reports.mkdir(mode=0o700)
        sync_dir(report_root)
        state = dict(release=str(root), image=pin, head=HEAD, run=str(report_root), input_sha256=hashes,
                     env_sha256=checksum(ENV), phase='planning', tasks=[])
        print(json.dumps(dict(private_reports=str(report_root), production_updates_started=False)), flush=True)
    else:
        require(len(sys.argv) == 3)
        report_root = Path(sys.argv[2])
        require(report_root.resolve().parent == (APP/'backups').resolve() and not report_root.is_symlink())
        require(re.fullmatch(r'english-catalog-[0-9a-f]{24}', report_root.name))
        require(report_root.stat().st_uid == os.geteuid() and stat.S_IMODE(report_root.stat().st_mode) == 0o700)
        if MARKER.exists():
            state = private_json(MARKER)
        else:
            require(mode in ('recover-finalize','finalize'), 'No recoverable English marker')
            receipt = private_json(report_root/'finalized.json')
            require(receipt.get('accepted') is True)
            state = receipt['state']
        require(state['run'] == str(report_root) and state['release'] == str(root) and state['image'] == pin and state['head'] == HEAD)
        require(state['env_sha256'] == checksum(ENV), 'Environment drift requires operator review')
        require(checksum(report_root/'snapshot.json') == state['snapshot_sha256'])
        inputs, reports = report_root/'reviewed-inputs', report_root/'reports'
        hashes = state['input_sha256']
        quiesce(state['tasks'], report_root.name, stop=mode != 'finalize')
        surviving = run(['docker','ps','--format','{{.Names}}','--filter','label=com.docker.compose.project=soulcuts',
                         '--filter','label=com.docker.compose.service=migrate',
                         '--filter','label=com.soulcuts.english-run='+report_root.name], timeout=30)
        quiesce(surviving.splitlines() if surviving else [], report_root.name, stop=mode != 'finalize')
    for table in FIELDS:
        name = 'prod-all-names-en.json' if table == 'products' else 'prod-all-category-names-en.json'
        require(checksum(inputs/name) == hashes[table], 'Reviewed input drifted')

    def save_phase(phase):
        state['phase'] = phase
        persist(MARKER, state, replace=MARKER.exists())

    def task(step, command, payload=None):
        require(checksum(ENV) == state['env_sha256'], 'Environment drift requires operator review')
        name = report_root.name+'-'+step
        require(name not in tasks, 'Fresh task name required')
        tasks.append(name)
        if MARKER.exists():
            state['tasks'] = list(dict.fromkeys([*state['tasks'], name]))
            save_phase('executing-'+step)
        args = ['docker','run','--rm','-i','--pull=never','--name',name,
                '--label','com.docker.compose.project=soulcuts',
                '--label','com.docker.compose.service=migrate',
                '--label','com.soulcuts.english-run='+report_root.name,
                '--network','container:'+cid('postgres'),'--memory=768m','--cpus=1','--pids-limit=128',
                '--user',str(os.geteuid())+':'+str(os.getegid()),
                '--env-file',str(ENV),'--env-file',str(APP/'env/postgres.env'),
                '-e','POSTGRES_HOST=postgres','-e','POSTGRES_PORT=5432',
                '-e','APP_ENV=production','-e','DEBUG=false',
                '-e','CORS_ORIGINS=https://soulcuts.com.ua,https://www.soulcuts.com.ua,https://admin.soulcuts.com.ua',
                '-e','BACKGROUND_WORKERS_ENABLED=false',
                '-v',str(root)+':/release-tools:ro',
                '-v',str(inputs)+':/reviewed-inputs:ro','-v',str(reports)+':/english-reports:rw',
                '--entrypoint','python',pin,'/release-tools/scripts/english-backfill-network-guard.py',*command]
        value = run(args, data=None if payload is None else json.dumps(payload), env=process_env)
        return json.loads(value)

    def db(step, operation, payload=None):
        return task(step, ['/release-tools/scripts/english-backfill-db.py',operation], payload)

    def cli(table, phase, baseline, target):
        name = 'prod-all-names-en.json' if table == 'products' else 'prod-all-category-names-en.json'
        module = 'app.utils.backfill_product_names_en' if table == 'products' else 'app.utils.backfill_category_names_en'
        report_name = table+'-'+phase+'.json'
        command = ['-m',module,'--input','/reviewed-inputs/'+name,'--report','/english-reports/'+report_name]
        if phase == 'apply':
            command.append('--apply')
        result = task(table+'-'+phase, command)
        count = len(target[table])
        updated = 0 if phase == 'idempotent' else planned_updates(baseline, target, table)
        require(result.get('status') == ('committed' if phase == 'apply' else 'dry_run')
                and result.get('count') == count and result.get('updated') == updated, 'Unexpected backfill outcome')
        report = private_json(reports/report_name)
        require(report.get('status') == ('prepared_apply' if phase == 'apply' else 'dry_run')
                and report.get('input_sha256') == hashes[table] and report.get('count') == count)
        return result

    try:
        if mode == 'apply':
            baseline = db('snapshot', 'snapshot')
            require(baseline['head'] == HEAD)
            target = targets_from_inputs(inputs, baseline)
            payload = dict(baseline=baseline, target=target)
            persist(report_root/'snapshot.json', payload)
            state['snapshot_sha256'] = checksum(report_root/'snapshot.json')
            for table in FIELDS:
                cli(table, 'dry-run', baseline, target)
            require(checksum(ENV) == state['env_sha256'], 'Environment drift requires operator review')
            # The durable recovery fence precedes either independently atomic apply.
            save_phase('prepared')
            results = {}
            for table in FIELDS:
                results[table] = cli(table, 'apply', baseline, target)
                save_phase(table+'-committed')
            for table in FIELDS:
                cli(table, 'idempotent', baseline, target)
            require(db('verify-original', 'verify', payload).get('verified') is True)
            require(checksum(ENV) == state['env_sha256'], 'Environment drift requires operator review')
            state['pre_restart_original_verified'] = True
            save_phase('verified')
            print(json.dumps(dict(applied=True, results=results, reports=str(report_root),
                                  recovery_marker_retained=True, services_started=False)))
            return
        payload = private_json(report_root/'snapshot.json')
        if mode == 'rollback':
            result = db('rollback', 'rollback', payload)
            require(result.get('rolled_back') is True)
            MARKER.unlink()
            sync_dir(APP)
            print(json.dumps(dict(rolled_back=True, backend_recovery_marker_retained=True, services_started=False)))
        elif mode == 'reconcile':
            for table in FIELDS:
                report = private_json(reports/(table+'-apply.json'))
                require(report.get('status') == 'prepared_apply' and report.get('input_sha256') == hashes[table]
                        and report.get('count') == len(payload['target'][table]))
            require(db('reconcile', 'verify', payload).get('verified') is True)
            require(checksum(ENV) == state['env_sha256'], 'Environment drift requires operator review')
            state['pre_restart_original_verified'] = True
            save_phase('verified')
            print(json.dumps(dict(reconciled=True, recovery_marker_retained=True, services_started=False)))
        elif mode == 'recover-finalize':
            require(state.get('pre_restart_original_verified') is True)
            require(db('recover-finalize', 'verify-live', payload).get('verified') is True)
            require(checksum(ENV) == state['env_sha256'], 'Environment drift requires operator review')
            if MARKER.exists():
                save_phase('verified')
            print(json.dumps(dict(finalization_reconciled=True, services_started=False,
                                  backend_recovery_marker_retained=True, english_marker=MARKER.exists())))
        else:
            require(os.environ.get('ENGLISH_RUNTIME_VERIFIED') == 'true' and state.get('pre_restart_original_verified') is True)
            result = db('verify-live', 'verify-live', payload)
            require(result.get('verified') is True)
            require(checksum(ENV) == state['env_sha256'])
            state['phase'] = 'verified'
            receipt_path = report_root/'finalized.json'
            if receipt_path.exists():
                receipt = private_json(receipt_path)
                require(receipt.get('accepted') is True)
                for key in ('release','image','head','run','input_sha256','env_sha256','snapshot_sha256','pre_restart_original_verified'):
                    require(receipt['state'][key] == state[key], 'Finalization receipt provenance differs')
                # A previous failed fsync may have left a readable but non-durable receipt.
                fd = os.open(receipt_path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    info = os.fstat(fd)
                    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                            and stat.S_IMODE(info.st_mode) == 0o600)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                sync_dir(report_root)
            else:
                persist(receipt_path, dict(accepted=True, state=state, result=result))
            if MARKER.exists():
                MARKER.unlink()
                sync_dir(APP)
            print(json.dumps(dict(accepted=True, products=552, categories=44, backend_recovery_marker_retained=True)))
    except BaseException:
        # A timed-out Docker CLI may leave its container running and writing.
        quiesce(tasks, report_root.name, stop=True)
        raise


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('English backfill failed closed; inspect protected reports and recovery fences') from None
