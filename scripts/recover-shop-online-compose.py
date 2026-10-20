#!/usr/bin/env python3
"""Bounded Compose-only recovery. Never changes env, DB, or either release fence."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

sys.dont_write_bytecode = True
APP = Path('/opt/soulcuts')
TOOLS = Path(__file__).resolve().parent
KEYS = ('SHOP_ORDER_OPERATIONS_ENABLED', 'SHOP_PAYMENTS_ENABLED', 'SHOP_MONOBANK_LIVE_TRANSPORT_ENABLED')
PROJECT = 'soulcuts'
PIN_KEYS = ('PUBLIC_SITE_IMAGE', 'BLOG_IMAGE', 'ADMIN_APP_IMAGE', 'SHOP_IMAGE',
            'BACKEND_IMAGE', 'CADDY_IMAGE', 'POSTGRES_IMAGE')
ENV_FILES = {'BACKEND_ENV_FILE': 'backend', 'POSTGRES_ENV_FILE': 'postgres',
             'CADDY_ENV_FILE': 'caddy', 'PUBLIC_SITE_ENV_FILE': 'public-site',
             'BLOG_ENV_FILE': 'blog', 'ADMIN_APP_ENV_FILE': 'admin-app', 'SHOP_ENV_FILE': 'shop'}
OVERLAY = ('services:\n  backend:\n    environment:\n'+''.join('      '+key+': "true"\n' for key in KEYS)).encode()


def require(value, message='Compose recovery safety condition failed'):
    if not value:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def private_bytes(path, mode=0o600):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == mode)
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            return stream.read()
    finally:
        os.close(fd)


def own_hashes():
    info = TOOLS.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700)
    result = {}
    for filename, variable in (
            ('recover-shop-online-compose.py', 'SHOP_ONLINE_COMPOSE_HELPER_SHA256'),
            ('run-shop-online-compose-recovery.sh', 'SHOP_ONLINE_COMPOSE_WRAPPER_SHA256')):
        expected = os.environ.get(variable, '')
        require(re.fullmatch(r'[0-9a-f]{64}', expected))
        result[filename] = sha(private_bytes(TOOLS/filename))
        require(result[filename] == expected, 'Reviewed recovery tool hash differs')
    return result


def report_path(state_dir):
    require(state_dir.parent == APP/'backups'
            and re.fullmatch(r'shop-online-activation-[0-9a-f]{24}', state_dir.name))
    return APP/'backups'/('shop-online-compose-recovery-'+state_dir.name.removeprefix('shop-online-activation-'))


def import_original(root):
    spec = importlib.util.spec_from_file_location('old_shop_activation', root/'scripts/activate-shop-online.py')
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    return original


def context(state_dir):
    hashes = own_hashes()
    report = report_path(state_dir)
    info = state_dir.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700)
    state_bytes = private_bytes(APP/'shop-online-activation-required')
    state = json.loads(state_bytes)
    root = Path(os.environ['EXPECTED_RELEASE'])
    require(root.is_dir() and not root.is_symlink() and root.resolve().parent == (APP/'releases').resolve())
    require(state['run'] == str(state_dir) and state['release'] == str(root)
            and state['image'] == os.environ.get('EXPECTED_BACKEND_IMAGE')
            and state['head'] == '0137_shop_online_payment'
            and state.get('pre_restart_original_verified') is True and state['phase'] == 'verified')
    require(set(state['tools']) == {'activate-shop-online.py', 'shop-online-config.py', 'run-shop-online-activation.sh'})
    # Check immutable old tools before importing any of their code.
    for name, expected in state['tools'].items():
        path = root/'scripts'/name
        require(re.fullmatch(r'[0-9a-f]{64}', expected) and path.is_file() and not path.is_symlink()
                and sha(path.read_bytes()) == expected)
    original = import_original(root)
    checked_root, pin = original.release_context()
    require(checked_root == root and pin == state['image'] and original.tool_hashes() == state['tools'])
    original.private(state_dir, 0o700, directory=True)
    before = original.read_private(state_dir/'before.env')
    after = original.read_private(state_dir/'after.env')
    require(sha(before) == state['before_sha256'] and sha(after) == state['after_sha256']
            and original.read_private(APP/'env/backend.env') == after)
    original.resync(APP/'env/backend.env')
    baseline_bytes = original.read_private(state_dir/'snapshot.json')
    plan_bytes = original.read_private(state_dir/'plan.json')
    proof_bytes = original.read_private(state_dir/'proof.json')
    require(sha(baseline_bytes) == state['snapshot_sha256'] and sha(plan_bytes) == state['plan_sha256']
            and sha(proof_bytes) == state['proof_sha256'])
    baseline, plan, proof = json.loads(baseline_bytes), json.loads(plan_bytes), json.loads(proof_bytes)
    original.validate_plan(plan, state['operator_id'])
    require(original.edit_env(before, plan['aliases']) == after)
    require(proof['env_sha256'] == state['before_sha256'] and proof['source_image'] == state['source_image']
            and proof['merchant_profile_sha256'] == plan['profile_sha256'] and proof['verified'] is True)
    accepted = (APP/'current').resolve(strict=True)
    require(accepted.parent == (APP/'releases').resolve() and accepted != root.resolve()
            and original.pin_for(accepted) == state['source_image'])
    require(os.environ.get('BACKEND_IMAGE') == pin
            and os.environ.get('BACKEND_ENV_FILE') == str(APP/'env/backend.env')
            and os.environ.get('POSTGRES_ENV_FILE') == str(APP/'env/postgres.env'))
    require(all(os.environ.get(key) == str(APP/('env/'+name+'.env')) for key, name in ENV_FILES.items()),
            'Foreign environment-file override')
    require(all(key in ENV_FILES for key in os.environ if key.endswith('_ENV_FILE')),
            'Unreviewed environment-file override')
    require(all(name not in os.environ for name in PIN_KEYS if name != 'BACKEND_IMAGE'),
            'Inherited image overrides are forbidden')
    bound = dict(release=str(root), image=pin, source_image=state['source_image'],
                 activation_run=str(state_dir), activation_state_sha256=sha(state_bytes),
                 env_sha256=sha(after), before_sha256=sha(before), activation_tools=state['tools'],
                 recovery_tools=hashes, project=PROJECT,
                 backend_env=str(APP/'env/backend.env'), postgres_env=str(APP/'env/postgres.env'),
                 postgres_env_sha256=sha(original.read_private(APP/'env/postgres.env')),
                 backend_marker_sha256=sha((APP/'backend-recovery-required').read_bytes()),
                 compose_sha256=sha((root/'docker-compose.prod.yml').read_bytes()),
                 versions_sha256=sha((root/'versions/production.env').read_bytes()))
    bound['environment_files'] = {key: dict(path=str(APP/('env/'+name+'.env')),
        sha256=sha(original.read_private(APP/('env/'+name+'.env')))) for key, name in ENV_FILES.items()}
    return original, root, pin, state, baseline, report, bound


def compose(root, overlay=None):
    args = ['docker', 'compose', '--project-name', PROJECT, '--env-file', str(root/'versions/production.env'),
            '-f', str(root/'docker-compose.prod.yml')]
    if overlay is not None:
        args += ['-f', str(overlay)]
    return args


def validate_delta(before, after, pin):
    require(isinstance(before, dict) and isinstance(after, dict))
    expected = copy.deepcopy(before)
    for service in ('backend', 'booking-sms-reminders'):
        require(before['services'][service]['image'] == pin)
    require(before.get('name') == PROJECT)
    environment = expected['services']['backend']['environment']
    for key in KEYS:
        require(type(environment.get(key)) is str and environment[key] == 'false',
                'Original backend override must be exactly false')
        environment[key] = 'true'
    require(after == expected, 'Resolved Compose differs outside the three reviewed backend flags')


def rendered(original, root, report, pin):
    require(original.read_private(report/'overlay.yml') == OVERLAY, 'Foreign overlay')
    before = json.loads(original.run(compose(root)+['config', '--format', 'json']))
    after = json.loads(original.run(compose(root, report/'overlay.yml')+['config', '--format', 'json']))
    validate_delta(before, after, pin)
    return before, after


def actual_writers(original, pin, *, require_running=None, require_flags=None):
    observations = {}
    for service in ('backend', 'booking-sms-reminders'):
        identifier = original.cid(service)
        details = json.loads(original.run(['docker', 'inspect', identifier]))
        require(isinstance(details, list) and len(details) == 1)
        item = details[0]
        require(item['Config']['Image'] == pin and type(item['State']['Running']) is bool)
        require(item['Config']['Labels'].get('com.docker.compose.project') == PROJECT
                and item['Config']['Labels'].get('com.docker.compose.service') == service)
        if require_running is not None:
            require(item['State']['Running'] is require_running)
        if service == 'backend':
            entries = [entry.split('=', 1) for entry in item['Config']['Env']]
            for key in KEYS:
                values = [value for name, value in entries if name == key]
                require(len(values) == 1)
                observations[key] = values[0]
            require(set(observations.values()) in ({'false'}, {'true'}), 'Unknown/mixed backend flag state')
            if require_flags is not None:
                require(set(observations.values()) == {require_flags})
        observations[service] = dict(id=identifier, running=item['State']['Running'],
                                     started_at=item['State'].get('StartedAt'))
    return observations


def checked_journal(original, report, bound):
    original.private(report, 0o700, directory=True)
    journal = original.json_private(report/'journal.json')
    require(journal['binding'] == bound, 'Recovery journal provenance drift')
    require(sha(original.read_private(report/'overlay.yml')) == journal['overlay_sha256'])
    for name in ('original-config.json', 'overlay-config.json'):
        require(sha(original.read_private(report/name)) == journal['config_sha256'][name])
    return journal


def execute(mode, state_dir):
    require(not sys.flags.optimize, 'Optimized execution is forbidden')
    original, root, pin, state, baseline, report, bound = context(state_dir)
    if mode == 'prepare':
        require(not report.exists() and not report.is_symlink(),
                'Existing recovery journal requires explicit reconcile, never blind retry')
        report.mkdir(mode=0o700)
        original.sync_dir(report.parent)
        original.persist_bytes(report/'overlay.yml', OVERLAY)
        before, after = rendered(original, root, report, pin)
        original.persist(report/'original-config.json', before)
        original.persist(report/'overlay-config.json', after)
        observations = actual_writers(original, pin, require_running=True, require_flags='false')
        journal = dict(version=1, binding=bound, phase='prepared_before_stop',
                       overlay_sha256=sha(OVERLAY), config_sha256={
                           'original-config.json': sha(canonical(before)),
                           'overlay-config.json': sha(canonical(after))}, observations=observations)
        original.persist(report/'journal.json', journal)
        original.resync(report/'journal.json')
    else:
        journal = checked_journal(original, report, bound)
        before, after = rendered(original, root, report, pin)
        require(before == original.json_private(report/'original-config.json')
                and after == original.json_private(report/'overlay-config.json'))
        if mode == 'reconcile':
            observations = actual_writers(original, pin)
            require(not (all(observations[service]['running'] for service in ('backend', 'booking-sms-reminders'))
                         and all(observations[key] == 'true' for key in KEYS)),
                    'Both pinned writers already run desired flags; primary runtime verification required, no restart')
            journal['observations'] = observations
            journal['phase'] = 'reconciled_before_stop'
        elif mode == 'after-stop':
            require(journal['phase'] in ('prepared_before_stop', 'reconciled_before_stop'))
            original.writers(False, pin)
            current = original.db_snapshot(state['operator_id'])
            original.verify_db(current, baseline, live=True)
            original.no_shop(current)
            # Only the fresh, stopped snapshot is frozen; initial worker/cart drift is legitimate.
            name = 'stopped-'+os.urandom(12).hex()+'.json'
            original.persist(report/name, current)
            journal.update(phase='stopped_snapshot', snapshot=name, snapshot_sha256=sha(canonical(current)))
        elif mode == 'before-restart':
            require(journal['phase'] == 'stopped_snapshot')
            original.writers(False, pin)
            require(re.fullmatch(r'stopped-[0-9a-f]{24}\.json', journal['snapshot']))
            snapshot_bytes = original.read_private(report/journal['snapshot'])
            require(sha(snapshot_bytes) == journal['snapshot_sha256'])
            current = original.db_snapshot(state['operator_id'])
            require(current == json.loads(snapshot_bytes), 'Database changed after stopped snapshot')
            original.verify_db(current, baseline, live=True)
            original.no_shop(current)
            journal['phase'] = 'restart_requested'
        elif mode == 'record-restart':
            require(journal['phase'] == 'restart_requested')
            original.writers(True, pin)
            journal['observations'] = actual_writers(original, pin, require_running=True, require_flags='true')
            journal['phase'] = 'restart_returned_not_accepted'
        else:
            raise RuntimeError('Unknown recovery phase')
        # Recheck env, both fences, old tools, Compose, and supplied hashes after all awaits.
        require(context(state_dir)[-1] == bound)
        original.persist(report/'journal.json', journal, replace=True)
        original.resync(report/'journal.json')
    require(context(state_dir)[-1] == bound)
    print(json.dumps(dict(phase=journal['phase'], private_recovery=str(report),
                          both_fences_retained=True, accepted=False)))


def main():
    require(len(sys.argv) == 3)
    require(sys.argv[1] in ('prepare', 'reconcile', 'after-stop', 'before-restart', 'record-restart'))
    execute(sys.argv[1], Path(sys.argv[2]))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Compose recovery failed closed; inspect private journal and retain both fences') from None
