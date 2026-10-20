#!/usr/bin/env python3
"""Environment-only Shop activation, with durable release fences and no DB writes."""
from datetime import datetime, timezone
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
HEAD = '0137_shop_online_payment'
TOOLS = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('shop_online_config', TOOLS/'shop-online-config.py')
CONFIG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIG)
FLAGS, FIELDS = CONFIG.FLAGS, CONFIG.FIELDS
SHOP_TABLES = ('shop_payment_intents', 'shop_payment_confirmations',
               'shop_mono_checkbox_receipts', 'shop_online_payment_requests')


def require(value, message='Shop activation safety condition failed'):
    if not value:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def private(path, mode=0o600, *, directory=False):
    info = path.lstat()
    require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == mode)
    return path


def read_private(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600)
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            return stream.read()
    finally:
        os.close(fd)


def persist_bytes(path, data, *, replace=False):
    if replace:
        fd, name = tempfile.mkstemp(prefix='.'+path.name+'-', dir=path.parent)
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
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


def persist(path, value, **kwargs):
    persist_bytes(path, canonical(value), **kwargs)


def json_private(path):
    return json.loads(read_private(path))


def resync(path):
    read_private(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600)
        os.fsync(fd)
    finally:
        os.close(fd)
    sync_dir(path.parent)


def run(args, *, data=None, timeout=120):
    result = subprocess.run(args, input=data, text=True, capture_output=True, timeout=timeout)
    require(result.returncode == 0, 'Controlled command failed; private output suppressed')
    return result.stdout.strip()


def cid(service):
    value = run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=soulcuts',
                 '--filter', 'label=com.docker.compose.service='+service])
    require(re.fullmatch(r'[0-9a-f]{12,64}', value))
    return value


def writers(running, pin):
    for service in ('backend', 'booking-sms-reminders'):
        container = cid(service)
        require(run(['docker', 'inspect', '--format', '{{.State.Running}}', container]) == str(running).lower())
        require(run(['docker', 'inspect', '--format', '{{.Config.Image}}', container]) == pin)


def pin_for(root):
    return run(['python3', str(root/'scripts/release-backend-pin.py'), str(root/'versions/production.env')])


def release_context():
    require(not sys.flags.optimize, 'Optimized execution is forbidden')
    owner = int((APP/'release.lock/pid').read_text().strip())
    require(owner == os.getppid() == int(os.environ.get('RELEASE_LOCK_OWNER_PID', '-1')))
    os.kill(owner, 0)
    root = Path(os.environ['EXPECTED_RELEASE'])
    require(root.is_dir() and not root.is_symlink() and root.resolve().parent == (APP/'releases').resolve())
    require(TOOLS == root.resolve()/'scripts', 'Candidate-adjacent tools required')
    marker = dict(line.split('=', 1) for line in (APP/'backend-recovery-required').read_text().splitlines())
    require(marker.get('release') == str(root) and marker.get('phase') == 'pending_acceptance')
    pin = pin_for(root)
    require(pin == os.environ.get('EXPECTED_BACKEND_IMAGE')
            and re.fullmatch(r'ghcr\.io/mharnichev/sc-be/api@sha256:[0-9a-f]{64}', pin))
    private(APP/'env/backend.env')
    private(APP/'env/postgres.env')
    return root, pin


def edit_env(original, aliases):
    require(set(aliases) == set(FIELDS))
    text = original.decode('utf-8')
    seen, output = set(), []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            output.append(line)
            continue
        require(not re.match(r'export\s', stripped), 'Export assignments are ambiguous')
        match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)', stripped)
        require(match, 'Unrecognized environment syntax')
        key = match[1]
        require(key not in seen, 'Duplicate environment assignment')
        seen.add(key)
        if key in aliases:
            ending = '\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else ''
            output.append(key+'='+canonical(aliases[key]).decode()+ending)
        else:
            output.append(line)
    missing = [key for key in FIELDS if key not in seen]
    require(not missing or original.endswith(b'\n'), 'Appending requires an original final newline')
    output.extend(key+'='+canonical(aliases[key]).decode()+'\n' for key in missing)
    return ''.join(output).encode()


def validate_proof(proof, env_hash, plan, accepted_pin, now=None):
    require(set(proof) == {'schema_version', 'verified', 'merchant_get_requests', 'merchant_profile_sha256',
                           'env_sha256', 'created_at', 'source_image'})
    require(type(proof['schema_version']) is int and proof['schema_version'] == 1
            and proof['verified'] is True and type(proof['merchant_get_requests']) is int
            and proof['merchant_get_requests'] == 1)
    require(proof['env_sha256'] == env_hash and proof['merchant_profile_sha256'] == plan['profile_sha256']
            and proof['source_image'] == accepted_pin)
    created = datetime.fromisoformat(proof['created_at'].replace('Z', '+00:00'))
    require(created.utcoffset() is not None and created.utcoffset().total_seconds() == 0)
    age = ((now or datetime.now(timezone.utc))-created).total_seconds()
    require(0 <= age <= 7200, 'Readiness proof expired or is future-dated')


def db_snapshot(operator_id):
    require(type(operator_id) is int and operator_id > 0)
    # psql generates only SELECT statements. Every query shares one read-only snapshot.
    query = r"""\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout='30s';
SET LOCAL lock_timeout='5s';
SELECT json_build_object('kind','identity','value',json_build_object('database',current_database(),'role',current_user,'version',current_setting('server_version_num'),'address',inet_server_addr()::text,'port',inet_server_port()));
SELECT json_build_object('kind','head','value',(SELECT json_agg(version_num ORDER BY version_num) FROM alembic_version));
SELECT json_build_object('kind','operator','value',(SELECT json_build_object('id',a.id,'is_active',a.is_active,'is_superuser',a.is_superuser,'can_record_sales',a.can_record_sales) FROM admin_users a WHERE a.id=OPERATOR_ID AND a.is_active AND (a.is_superuser OR a.can_record_sales) AND NOT EXISTS(SELECT 1 FROM masters m WHERE m.admin_user_id=a.id)));
SELECT json_build_object('kind','grants','value',json_build_object('admins',(SELECT COALESCE(jsonb_agg((SELECT jsonb_object_agg(k,v) FROM jsonb_each(to_jsonb(a)) AS e(k,v) WHERE jsonb_typeof(v)='boolean' OR k='id') ORDER BY id),'[]') FROM admin_users a),'masters',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',id,'admin_user_id',admin_user_id,'is_active',is_active) ORDER BY id),'[]') FROM masters m)));
SELECT json_build_object('kind','shop_orders','value',count(*)) FROM orders WHERE channel='shop';
SELECT json_build_object('kind','inventory','value',COALESCE(jsonb_agg(to_jsonb(c) ORDER BY table_name,ordinal_position),'[]')) FROM information_schema.columns c WHERE table_schema='public' AND table_name IN(SELECT tablename FROM pg_tables WHERE schemaname='public');
SELECT format('SELECT json_build_object(''kind'',''table'',''name'',%L,''value'',json_build_object(''rows'',count(*),''sha256'',encode(sha256(convert_to(COALESCE(string_agg(h,'''' ORDER BY h),''''),''UTF8'')),''hex''))) FROM (SELECT encode(sha256(convert_to(to_jsonb(t)::text,''UTF8'')),''hex'') h FROM public.%I t) q;',tablename,tablename) FROM pg_tables WHERE schemaname='public' ORDER BY tablename
\gexec
SELECT format('SELECT json_build_object(''kind'',''sequence'',''name'',%L,''value'',json_build_object(''last_value'',last_value,''log_cnt'',log_cnt,''is_called'',is_called)) FROM public.%I;',sequencename,sequencename) FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename
\gexec
ROLLBACK;
""".replace('OPERATOR_ID', str(operator_id))
    raw = run(['docker', 'exec', '-i', cid('postgres'), 'sh', '-eu', '-c',
               'unset PGHOSTADDR PGSERVICE PGSERVICEFILE; exec psql -X -qAt -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 5432 -U "$POSTGRES_USER" -d barbershop_platform'], data=query)
    result = {'tables': {}, 'sequences': {}}
    for line in raw.splitlines():
        row = json.loads(line)
        key = row['kind']
        if key in ('table', 'sequence'):
            result['tables' if key == 'table' else 'sequences'][row['name']] = row['value']
        else:
            require(key not in result)
            result[key] = row['value']
    require(result.get('head') == [HEAD] and result.get('identity', {}).get('database') == 'barbershop_platform')
    require(isinstance(result.get('operator'), dict) and result['operator'].get('id') == operator_id)
    require(set(SHOP_TABLES).issubset(result['tables']) and 'grants' in result and 'inventory' in result)
    return result


def no_shop(snapshot):
    require(snapshot['shop_orders'] == 0 and all(snapshot['tables'][name]['rows'] == 0 for name in SHOP_TABLES),
            'Existing Shop facts require separate financial review')


def verify_db(current, baseline, *, live=False):
    if not live:
        require(current == baseline, 'Database changed while activation writers were stopped')
        no_shop(current)
    else:
        for key in ('identity', 'head', 'operator', 'grants'):
            require(current[key] == baseline[key], 'Live database provenance changed')


def tool_hashes():
    return {name: sha((TOOLS/name).read_bytes()) for name in
            ('activate-shop-online.py', 'shop-online-config.py', 'run-shop-online-activation.sh')}


def quiesce(prefix):
    require(re.fullmatch(r'shop-online-activation-[0-9a-f]{24}', prefix))
    found = run(['docker', 'ps', '--format', '{{.ID}} {{.Names}}', '--filter',
                 'label=com.soulcuts.shop-online-run='+prefix], timeout=30)
    for line in found.splitlines():
        identifier, name = line.split()
        require(re.fullmatch(r'[0-9a-f]{12,64}', identifier) and name.startswith(prefix+'-'))
        run(['docker', 'stop', '--time', '5', identifier], timeout=30)
    require(not run(['docker', 'ps', '-q', '--filter', 'label=com.soulcuts.shop-online-run='+prefix], timeout=30),
            'Read-only task cleanup failed')


def cleanup_release(root):
    values = run(['docker', 'ps', '--format', '{{.Names}}', '--filter',
                  'label=com.soulcuts.shop-online-release='+str(root)], timeout=30)
    prefixes = set()
    for name in values.splitlines():
        match = re.fullmatch(r'(shop-online-activation-[0-9a-f]{24})-(?:plan|verify)-[0-9a-f]{8}', name)
        require(match, 'Foreign read-only task identity')
        prefixes.add(match[1])
    for prefix in prefixes:
        quiesce(prefix)


def candidate(root, pin, env_path, mode, operator_id, prefix):
    name = prefix+'-'+mode+'-'+secrets.token_hex(4)
    args = ['docker', 'run', '--rm', '-i', '--pull=never', '--name', name,
            '--label', 'com.soulcuts.shop-online-run='+prefix,
            '--label', 'com.soulcuts.shop-online-release='+str(root), '--network=none',
            '--memory=768m', '--cpus=1', '--pids-limit=128', '--user', f'{os.geteuid()}:{os.getegid()}',
            '--env-file', str(APP/'env/postgres.env'), '--env-file', str(env_path),
            '-e', 'POSTGRES_HOST=postgres', '-e', 'POSTGRES_PORT=5432',
            '-e', 'APP_ENV=production', '-e', 'BACKGROUND_WORKERS_ENABLED=false',
            '-v', str(root)+':/release-tools:ro', '--entrypoint', 'python', pin,
            '/release-tools/scripts/shop-online-config.py', mode, str(operator_id)]
    return json.loads(run(args))


def validate_plan(plan, operator_id):
    require(set(plan) == {'aliases', 'profile_sha256'} and set(plan['aliases']) == set(FIELDS))
    aliases = plan['aliases']
    require(all(aliases[key] is True for key in FLAGS)
            and type(aliases['SHOP_ONLINE_PAYMENT_OPERATOR_ID']) is int
            and aliases['SHOP_ONLINE_PAYMENT_OPERATOR_ID'] == operator_id)
    profile = aliases['SHOP_MONOBANK_PROFILE']
    require(set(profile) == {'id', 'merchant_id', 'token_sha256', 'environment', 'external_fiscalization_disabled'}
            and profile['id'] == 'soulcuts-shop-online-tax8-v1' and profile['environment'] == 'production'
            and profile['external_fiscalization_disabled'] is False
            and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', profile['merchant_id'])
            and re.fullmatch(r'[0-9a-f]{64}', profile['token_sha256']))
    require(aliases['SHOP_ONLINE_PAYMENT_FISCAL_POLICY'] == dict(id='soulcuts-shop-tax8-v1', tax_codes=[8], unit='шт.'))
    require(plan['profile_sha256'] == sha(canonical(profile)))


def main():
    os.umask(0o077)
    require(len(sys.argv) >= 3)
    mode = sys.argv[1]
    require(mode in ('apply', 'rollback', 'reconcile', 'recover-finalize', 'finalize'))
    require(len(sys.argv) == (4 if mode == 'apply' else 3))
    root, pin = release_context()
    env = APP/'env/backend.env'
    marker = APP/'shop-online-activation-required'
    writers(mode == 'finalize', pin)
    tasks_started = False
    if mode == 'apply':
        require(not marker.exists() and not marker.is_symlink())
        proof_dir = Path(sys.argv[2])
        require(proof_dir.parent == APP/'backups' and re.fullmatch(r'shop-online-readiness-[a-zA-Z0-9_-]+', proof_dir.name))
        private(proof_dir, 0o700, directory=True)
        proof_bytes = read_private(proof_dir/'proof.json')
        proof = json.loads(proof_bytes)
        operator_id = int(sys.argv[3])
        require(operator_id > 0)
        accepted = (APP/'current').resolve(strict=True)
        require(accepted.parent == (APP/'releases').resolve() and accepted != root.resolve())
        source_pin = pin_for(accepted)
        original = read_private(env)
        edit_env(original, dict.fromkeys(FIELDS, None))
        report = APP/'backups'/('shop-online-activation-'+secrets.token_hex(12))
        report.mkdir(mode=0o700)
        sync_dir(report.parent)
        prefix = report.name
        state = dict(version=1, release=str(root), image=pin, head=HEAD, run=str(report),
                     operator_id=operator_id, source_image=source_pin, tools=tool_hashes(),
                     proof_sha256=sha(proof_bytes), before_sha256=sha(original), tasks_prefix=prefix,
                     pre_restart_original_verified=False, phase='planning')
        print(json.dumps({'private_state': str(report), 'environment_changed': False}), flush=True)
    else:
        report = Path(sys.argv[2])
        require(report.parent == APP/'backups' and re.fullmatch(r'shop-online-activation-[0-9a-f]{24}', report.name))
        private(report, 0o700, directory=True)
        if marker.exists() or marker.is_symlink():
            state = json_private(marker)
        else:
            require(mode in ('recover-finalize', 'finalize', 'rollback'))
            receipt = json_private(report/('rolled-back.json' if mode == 'rollback' else 'finalized.json'))
            require(receipt.get('restored' if mode == 'rollback' else 'finalized') is True)
            state = receipt['state']
        require(state['release'] == str(root) and state['image'] == pin and state['head'] == HEAD
                and state['run'] == str(report) and state['tasks_prefix'] == report.name
                and state['tools'] == tool_hashes())
        prefix, operator_id = state['tasks_prefix'], state['operator_id']
        quiesce(prefix)

    def save(phase):
        state['phase'] = phase
        persist(marker, state, replace=marker.exists())

    def verify_config(path):
        nonlocal tasks_started
        require(tool_hashes() == state['tools'])
        tasks_started = True
        value = candidate(root, pin, path, 'verify', operator_id, prefix)
        require(value == plan)

    try:
        if mode == 'apply':
            tasks_started = True
            plan = candidate(root, pin, env, 'plan', operator_id, prefix)
            validate_plan(plan, operator_id)
            validate_proof(proof, sha(original), plan, source_pin)
            require(read_private(env) == original)
            baseline = db_snapshot(operator_id)
            no_shop(baseline)
            staged = edit_env(original, plan['aliases'])
            persist_bytes(report/'before.env', original)
            persist_bytes(report/'after.env', staged)
            persist_bytes(report/'proof.json', proof_bytes)
            persist(report/'snapshot.json', baseline)
            persist(report/'plan.json', plan)
            state.update(after_sha256=sha(staged), snapshot_sha256=sha(canonical(baseline)),
                         plan_sha256=sha(canonical(plan)))
            verify_config(report/'after.env')
            require(read_private(env) == original)
            verify_db(db_snapshot(operator_id), baseline)
            validate_proof(proof, sha(original), plan, source_pin)
            require((APP/'current').resolve(strict=True) == accepted and pin_for(accepted) == source_pin)
            writers(False, pin)
            # Recovery fence and all replacement material are durable before the sole mutation.
            save('prepared')
            persist_bytes(env, staged, replace=True)
            save('env_replaced')
        else:
            original, staged = read_private(report/'before.env'), read_private(report/'after.env')
            require(sha(original) == state['before_sha256'] and sha(staged) == state['after_sha256'])
            require(sha(read_private(report/'proof.json')) == state['proof_sha256'])
            baseline = json_private(report/'snapshot.json')
            plan = json_private(report/'plan.json')
            require(sha(canonical(baseline)) == state['snapshot_sha256']
                    and sha(canonical(plan)) == state['plan_sha256'])
            validate_plan(plan, operator_id)
            require(edit_env(original, plan['aliases']) == staged)

        actual = read_private(env)
        if mode == 'rollback':
            require(actual in (original, staged), 'Foreign environment; rollback refused')
            verify_db(db_snapshot(operator_id), baseline)
            if actual != original:
                persist_bytes(env, original, replace=True)
            verify_db(db_snapshot(operator_id), baseline)
            require(read_private(env) == original)
            rollback_path = report/'rolled-back.json'
            rollback_record = {'state': state, 'restored': True}
            if rollback_path.exists() or rollback_path.is_symlink():
                require(json_private(rollback_path) == rollback_record)
                resync(rollback_path)
            else:
                persist(rollback_path, rollback_record)
            if marker.exists():
                marker.unlink()
                sync_dir(APP)
        else:
            require(actual == staged, 'Environment drift; manual review required')
            verify_config(env)
            live = mode in ('recover-finalize', 'finalize')
            if live:
                require(state.get('pre_restart_original_verified') is True)
            verify_db(db_snapshot(operator_id), baseline, live=live)
            require(read_private(env) == staged and tool_hashes() == state['tools'])
            if mode in ('apply', 'reconcile'):
                state['pre_restart_original_verified'] = True
                save('verified')
            elif mode == 'finalize':
                require(os.environ.get('SHOP_ONLINE_RUNTIME_VERIFIED') == 'true')
                receipt_path = report/'finalized.json'
                if receipt_path.exists() or receipt_path.is_symlink():
                    receipt = json_private(receipt_path)
                    require(receipt.get('finalized') is True and receipt['state'] == state)
                    resync(receipt_path)
                else:
                    persist(receipt_path, {'finalized': True, 'state': state, 'live_verified': True})
                if marker.exists():
                    marker.unlink()
                    sync_dir(APP)
        print(json.dumps({'operation': mode, 'verified': True, 'backend_fence_retained': True,
                          'activation_fence': marker.exists(), 'services_started': False}))
    finally:
        if tasks_started:
            quiesce(prefix)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Shop activation failed closed; inspect private state and release fences') from None
