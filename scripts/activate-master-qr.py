"""Snapshot or apply exactly the authorized Master QR flags and grants.

Run under the normal release mutex. Activation requires both writers stopped,
schema 0134, no real POS history and an unchanged private configuration snapshot.
No bank or business-operation endpoints are called.
"""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

if sys.flags.optimize:
    raise SystemExit('Optimized execution is forbidden for Master QR activation')

APP = Path('/opt/soulcuts')
ENV = APP / 'env/backend.env'
FIELDS = ['id', 'is_active', 'is_superuser', 'can_post_inventory',
          'can_accept_qr_payments', 'can_record_sales', 'can_manage_shipments',
          'can_fiscalize_returns', 'can_fiscalize_sales', 'can_manage_fiscal_settings']
FLAGS = ['MASTER_MONO_ENABLED', 'MASTER_MONO_INVOICE_CREATE_ENABLED',
         'MASTER_MONOBANK_LIVE_TRANSPORT_ENABLED', 'MONO_CHECKBOX_AUTO_ENABLED']

def require(condition, message='Master QR safety condition failed'):
    if not condition:
        raise RuntimeError(message)

def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=60, **kwargs)
    if result.returncode:
        raise RuntimeError('Controlled command failed; private output suppressed')
    return result.stdout.strip()

def cid(service, running=True):
    args = ['docker', 'ps'] + ([] if running else ['-a'])
    result = run(args + ['-q','--filter','label=com.docker.compose.project=soulcuts',
                         '--filter','label=com.docker.compose.service=' + service])
    require(result and '\n' not in result)
    return result

def query(sql):
    return run(['docker','exec','-i',cid('postgres'),'sh','-c',
                'exec psql -X -q -v ON_ERROR_STOP=1 -At -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],input=sql)

def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())

def atomic_private_write(path, data):
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name,path)
        directory = os.open(path.parent,os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(name): os.unlink(name)

def checkpoint(phase):
    """Test seam for interruption between durable boundaries; no runtime switch."""

def replacement_env(original):
    result = []
    seen = {key:0 for key in FLAGS}
    for line in original.decode().splitlines(keepends=True):
        match = re.match(r'^\s*(export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=',line)
        if match and match[2] in FLAGS:
            key = match[2]
            require(match[1] is None,'Export-prefixed working flags require normalization by operator')
            require(line.partition('=')[2].strip() == 'false','Working flag is not exactly disabled')
            seen[key] += 1
            line = key + '=true' + ('\n' if line.endswith('\n') else '')
        result.append(line)
    require(all(count == 1 for count in seen.values()),'Ambiguous working flag assignments')
    return ''.join(result).encode()

def all_grants_sql():
    return 'SELECT coalesce(jsonb_agg(to_jsonb(a) ORDER BY a.id),\'[]\'::jsonb) FROM (SELECT ' + ','.join(FIELDS) + ' FROM admin_users ORDER BY id) a'

def eligibility_sql():
    return 'SELECT coalesce(json_agg(a.id ORDER BY a.id),\'[]\'::json) FROM admin_users a WHERE a.is_active AND NOT a.is_superuser AND EXISTS(SELECT 1 FROM masters m WHERE m.admin_user_id=a.id AND m.is_active)'

def changed_rows(before, targets):
    return [{**row, **({'can_record_sales': True, 'can_accept_qr_payments': True}
                      if row['id'] in targets else {})} for row in before]

def grants_transaction(before, after, targets):
    expected = json.dumps(before, separators=(',', ':'))
    desired = json.dumps(after, separators=(',', ':'))
    ids = ','.join(str(int(value)) for value in targets)
    # Only integer IDs and booleans enter the generated statement.
    require('$' not in expected + desired and targets)
    cases = ','.join('(%d,%s,%s)' % (row['id'], str(row['can_record_sales']).lower(),
                                    str(row['can_accept_qr_payments']).lower())
                     for row in after if row['id'] in targets)
    return f'''BEGIN; SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='15s';
DO $qr$ DECLARE actual jsonb; touched integer; BEGIN
 PERFORM id FROM admin_users ORDER BY id FOR UPDATE;
 PERFORM id FROM masters WHERE admin_user_id IN ({ids}) ORDER BY id FOR UPDATE;
 {all_grants_sql()} INTO actual;
 IF actual IS DISTINCT FROM '{expected}'::jsonb THEN RAISE EXCEPTION 'Grant snapshot changed'; END IF;
 IF ({eligibility_sql()})::jsonb IS DISTINCT FROM '{json.dumps(targets)}'::jsonb THEN RAISE EXCEPTION 'Eligible master set changed'; END IF;
 UPDATE admin_users a SET can_record_sales=v.sales,can_accept_qr_payments=v.qr
 FROM (VALUES {cases}) AS v(id,sales,qr)
 WHERE a.id=v.id AND a.id IN ({ids}) AND a.is_active AND NOT a.is_superuser
 AND EXISTS(SELECT 1 FROM masters m WHERE m.admin_user_id=a.id AND m.is_active);
 GET DIAGNOSTICS touched=ROW_COUNT;
 IF touched!={len(targets)} THEN RAISE EXCEPTION 'Unexpected grant count'; END IF;
 {all_grants_sql()} INTO actual;
 IF actual IS DISTINCT FROM '{desired}'::jsonb THEN RAISE EXCEPTION 'Unrelated grant changed'; END IF;
END $qr$; COMMIT;'''

def main():
    os.umask(0o077)
    lock = APP / 'release.lock'
    require(lock.is_dir(),'Normal release mutex required')
    owner = int((lock/'pid').read_text().strip())
    require(owner == os.getppid() == int(os.environ.get('RELEASE_LOCK_OWNER_PID','-1')),'Owning release wrapper required')
    os.kill(owner,0)
    require(not ENV.is_symlink() and ENV.stat().st_uid == os.geteuid())
    require(stat.S_IMODE(ENV.stat().st_mode) == 0o600)
    marker = APP / 'master-qr-activation-required'
    mode = sys.argv[1]
    if mode == 'snapshot':
        require(not marker.exists(),'Prior activation recovery is required')
        before = json.loads(query('BEGIN READ ONLY; ' + all_grants_sql() + '; COMMIT;'))
        targets = json.loads(query('BEGIN READ ONLY; ' + eligibility_sql() + '; COMMIT;'))
        require(len(targets) == 5)
        require(all(not row['can_record_sales'] and not row['can_accept_qr_payments'] for row in before if row['id'] in targets))
        root = APP / 'backups' / ('master-qr-activation-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        root.mkdir(mode=0o700)
        original = ENV.read_bytes()
        private_write(root / 'backend.env.before', original)
        private_write(root / 'grants.before.json', json.dumps({'rows': before, 'targets': targets}).encode())
        after = changed_rows(before, targets)
        private_write(root / 'rollback-grants.sql', grants_transaction(after, before, targets).encode())
        require(ENV.read_bytes() == original)
        print(json.dumps({'snapshot':str(root),'eligible_masters':len(targets),'config_or_grants_changed':False}))
        return
    require(mode in ('apply','rollback','finalize'))
    backend_marker=dict(line.split('=',1) for line in (APP/'backend-recovery-required').read_text().splitlines() if '=' in line)
    expected_release=os.environ.get('EXPECTED_RELEASE','')
    require(backend_marker.get('phase')=='pending_acceptance' and expected_release and backend_marker.get('release')==expected_release,
            'Matching pending backend release is required throughout activation')
    release=Path(expected_release)
    require(release.is_dir() and release.resolve().is_relative_to((APP/'releases').resolve()))
    root = Path(sys.argv[2])
    require(root.parent.resolve() == (APP/'backups').resolve() and not root.is_symlink())
    require(stat.S_IMODE(root.stat().st_mode)==0o700 and root.stat().st_uid==os.geteuid())
    saved = json.loads((root / 'grants.before.json').read_text())
    original = (root / 'backend.env.before').read_bytes()
    replacement = replacement_env(original)
    after = changed_rows(saved['rows'], saved['targets'])
    if mode == 'finalize':
        require(os.environ.get('MASTER_QR_RUNTIME_VERIFIED')=='true','Explicit runtime acceptance required')
        state=json.loads(marker.read_text())
        require(state['snapshot']==str(root) and state['phase']=='env_replaced')
        require(ENV.read_bytes()==replacement)
        require(json.loads(query('BEGIN READ ONLY; ' + all_grants_sql() + '; COMMIT;'))==after)
        for service in ('backend','booking-sms-reminders'):
            require(run(['docker','inspect','--format','{{.State.Running}}',cid(service)])=='true')
        marker.unlink()
        print(json.dumps({'activation_accepted':True,'business_operations_created':0}))
        return
    for service in ('backend','booking-sms-reminders'):
        require(run(['docker','inspect','--format','{{.State.Running}}',cid(service,False)])=='false')
    if mode=='rollback':
        state=json.loads(marker.read_text())
        require(state['snapshot']==str(root))
        require(ENV.read_bytes() in (original,replacement),'Concurrent env change requires operator reconciliation')
        require(query('BEGIN READ ONLY; SELECT count(*) FROM master_mono_create_requests; COMMIT;')=='0')
        current=json.loads(query('BEGIN READ ONLY; '+all_grants_sql()+'; COMMIT;'))
        if current==after:
            query((root/'rollback-grants.sql').read_text())
        else:
            require(current==saved['rows'],'Concurrent grants require operator reconciliation')
        atomic_private_write(ENV,original)
        marker.unlink()
        print(json.dumps({'activation_rolled_back':True,'business_operations_changed':False}))
        return
    require(not marker.exists(),'Activation recovery marker already exists')
    require(ENV.read_bytes()==original,'Environment changed since snapshot')
    require(query('BEGIN READ ONLY; SELECT version_num FROM alembic_version; COMMIT;')=='0134_shop_canonical_collation')
    require(query("BEGIN READ ONLY; SELECT count(*) FROM orders WHERE channel='backoffice_pos' AND NOT simulation; COMMIT;")=='0')
    require(query("BEGIN READ ONLY; SELECT count(*) FROM orders WHERE NOT simulation AND status::text NOT IN ('completed','cancelled'); COMMIT;")=='0')
    require(query('BEGIN READ ONLY; SELECT count(*) FROM master_mono_create_requests; COMMIT;')=='0')
    fd, name = tempfile.mkstemp(prefix='.backend.master-qr-enable-', dir=ENV.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(replacement); stream.flush(); os.fsync(stream.fileno())
        require(ENV.read_bytes()==original)
        state={'snapshot':str(root),'phase':'prepared'}
        private_write(marker,json.dumps(state).encode())
        directory=os.open(marker.parent,os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
        query(grants_transaction(saved['rows'], after, saved['targets']))
        state['phase']='grants_committed'; atomic_private_write(marker,json.dumps(state).encode())
        checkpoint('grants_committed')
        require(ENV.read_bytes()==original)
        os.replace(name, ENV)
        directory = os.open(ENV.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
        state['phase']='env_replaced'; atomic_private_write(marker,json.dumps(state).encode())
        checkpoint('env_replaced')
    finally:
        if os.path.exists(name): os.unlink(name)
    require(stat.S_IMODE(ENV.stat().st_mode)==0o600)
    require(json.loads(query('BEGIN READ ONLY; '+all_grants_sql()+'; COMMIT;'))==after)
    print(json.dumps({'granted_active_linked_masters':len(saved['targets']),
                      'changed_grants':['can_record_sales','can_accept_qr_payments'],
                      'enabled_flags':FLAGS,'unrelated_grants_and_env_preserved':True,
                      'business_operations_created':0,'services_started':False,
                      'activation_marker_retained':True}))

if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Master QR configuration operation refused or failed; inspect private snapshot, no secrets printed') from None
