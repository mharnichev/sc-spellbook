#!/usr/bin/env python3
"""Rehearse an upgrade on an isolated, private production copy, never in place."""
import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import uuid


HEAD = "0139_shop_input_guards"
BASE = "0110_nova_poshta_directory"
SOURCE_HEADS = (BASE, "0129_shop_ingress_limits", "0134_shop_canonical_collation", "0136_category_names_en", "0137_shop_online_payment", "0138_shop_content_en")


def source_archive_name(head):
    if head not in SOURCE_HEADS:
        raise RuntimeError("Unreviewed source baseline")
    return "production-" + head.split("_", 1)[0] + ".dump"


def verify_source_copy(sql, expected):
    actual = sql("upgrade_copy", "SELECT version_num FROM alembic_version")
    if actual != expected:
        raise RuntimeError("Source copy is not the reviewed production baseline")
    collation = sql("upgrade_copy", "SELECT datcollate FROM pg_database WHERE datname=current_database()")
    ctype = sql("upgrade_copy", "SELECT datctype FROM pg_database WHERE datname=current_database()")
    if collation != "en_US.utf8" or ctype != "en_US.utf8":
        raise RuntimeError("Source copy does not match the reviewed production locale")
    return dict(source_head=actual, source_collation=collation, source_ctype=ctype)


ENGLISH_INPUTS = (
    ('products', 'prod-all-names-en.json', 'app.utils.backfill_product_names_en', 552),
    ('categories', 'prod-all-category-names-en.json', 'app.utils.backfill_category_names_en', 44),
)
CONTENT_INPUTS = (
    ('products', 'prod-public-dynamic-en.json', 'app.utils.backfill_shop_content_en', 228),
)
CONTENT_SHA256 = '992d43055f3266de376be3b85085078633c4b68c4c7412fba4681a155bd1110a'
CONTENT_FIELDS = ('description_en', 'short_description_en', 'ingredients_en')
CONTENT_VECTOR_SQL = "SELECT coalesce(json_agg(t ORDER BY id),'[]') FROM (SELECT id, description_en, short_description_en, ingredients_en FROM products) t"
ENGLISH_COUNTS_SQL = """SELECT json_build_object(
 'products',(SELECT count(*) FROM products WHERE name_en IS NOT NULL AND product_type_en IS NOT NULL),
 'categories',(SELECT count(*) FROM categories WHERE name_en IS NOT NULL))"""


def seal_english_inputs(directory, hashes, output, *, backup_root=None, definitions=ENGLISH_INPUTS):
    directory = directory.resolve()
    backup_root = Path('/opt/soulcuts/backups') if backup_root is None else backup_root
    if (directory.parent != backup_root.resolve() or directory.stat().st_uid != os.geteuid()
            or stat.S_IMODE(directory.stat().st_mode) != 0o700):
        raise RuntimeError('English inputs require an owned private backup directory')
    sealed = output / 'reviewed-inputs'
    sealed.mkdir(mode=0o700)
    result = {}
    for kind, name, _, count in definitions:
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise RuntimeError('English input must be a private regular file')
        data = path.read_bytes()
        checksum = hashlib.sha256(data).hexdigest()
        if checksum != hashes[kind]:
            raise RuntimeError('English input checksum differs from the reviewed bundle')
        payload = json.loads(data)
        if payload.get('count') != count or len(payload.get(kind, [])) != count:
            raise RuntimeError('English input count differs from the reviewed complete catalog')
        fd = os.open(sealed/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        result[kind] = checksum
    sealed.chmod(0o500)
    fd = os.open(sealed, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    fd = os.open(output, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return sealed, result


def rehearse_english(execute, sql, candidate, network, env, run, output, inputs, hashes,
                     *, definitions=ENGLISH_INPUTS):
    content_target = None
    if definitions == CONTENT_INPUTS:
        baseline = json.loads(sql('upgrade_copy', CONTENT_VECTOR_SQL))
        if any(row[field] is not None for row in baseline for field in CONTENT_FIELDS):
            raise RuntimeError('New content migration unexpectedly populated English fields')
        content_target = {row['id']: row for row in baseline}
        reviewed = json.loads((inputs/CONTENT_INPUTS[0][1]).read_bytes())
        rows = reviewed['products']
        if len({row['id'] for row in rows}) != 228:
            raise RuntimeError('Duplicate reviewed content identities')
        for row in rows:
            if row['id'] not in content_target or set(row['translations']) != set(CONTENT_FIELDS):
                raise RuntimeError('Content target differs from the reviewed catalog')
            content_target[row['id']].update(row['translations'])
    reports = output/'english-reports'
    reports.mkdir(mode=0o700)
    fd = os.open(output, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    summaries = {}
    # Two separate transactions, never presented as one combined atomic update.
    for phase in ('dry-run', 'apply', 'idempotent'):
        for kind, name, module, count in definitions:
            if hashlib.sha256((inputs/name).read_bytes()).hexdigest() != hashes[kind]:
                raise RuntimeError('Sealed English input drifted')
            report_name = kind+'-'+phase+'.json'
            command = ['docker','run','--rm','--name',run+'-english-'+kind+'-'+phase,
                       '--user',str(os.geteuid())+':'+str(os.getegid()),
                       '--network',network,'--env-file',str(env),'--memory=768m','--cpus=1',
                       '--pids-limit=128','--pull=never','-v',str(inputs)+':/reviewed-inputs:ro',
                       '-v',str(reports)+':/rehearsal-reports:rw','--entrypoint','python',candidate,
                       '-m',module,'--input','/reviewed-inputs/'+name,
                       '--report','/rehearsal-reports/'+report_name]
            if phase == 'apply':
                command.append('--apply')
            summary = json.loads(execute(command))
            updated = 0 if phase == 'idempotent' else count
            if (summary.get('count') != count or summary.get('updated') != updated
                    or summary.get('status') != ('committed' if phase == 'apply' else 'dry_run')):
                raise RuntimeError('Unexpected English backfill summary')
            report_path = reports/report_name
            if (report_path.is_symlink() or not report_path.is_file()
                    or report_path.stat().st_uid != os.geteuid() or stat.S_IMODE(report_path.stat().st_mode) != 0o600):
                raise RuntimeError('English rollback report is not a private regular file')
            report = json.loads(report_path.read_text())
            if (report.get('input_sha256') != hashes[kind] or report.get('count') != count
                    or report.get('status') != ('prepared_apply' if phase == 'apply' else 'dry_run')):
                raise RuntimeError('English rollback report contract differs')
            summaries[kind+'-'+phase] = summary
    if definitions == CONTENT_INPUTS:
        actual = json.loads(sql('upgrade_copy', CONTENT_VECTOR_SQL))
        if actual != sorted(content_target.values(), key=lambda row: row['id']):
            raise RuntimeError('Applied English content differs from the complete reviewed vector')
        if sql('upgrade_copy', 'SELECT count(*) FROM categories WHERE description_en IS NOT NULL') != '0':
            raise RuntimeError('Unreviewed category content changed')
        return dict(summaries=summaries, input_sha256=hashes,
                    transactions='one atomic product content transaction', full_vector_verified=True)
    counts = json.loads(sql('upgrade_copy', ENGLISH_COUNTS_SQL))
    if counts != {'products':552, 'categories':44}:
        raise RuntimeError('English coverage differs from the complete reviewed inputs')
    return dict(counts=counts, summaries=summaries, input_sha256=hashes,
                transactions='separate products and categories')


SCHEMA_SQL = """SELECT jsonb_build_object(
 'constraints',(SELECT COALESCE(jsonb_agg(jsonb_build_array(c.conrelid::regclass::text,c.conname,c.contype,pg_get_constraintdef(c.oid,true),c.condeferrable,c.condeferred,c.convalidated) ORDER BY c.conrelid::regclass::text,c.conname),'[]'::jsonb) FROM pg_constraint c WHERE c.connamespace='public'::regnamespace),
 'triggers',(SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,t.tgname,pg_get_triggerdef(t.oid,true),t.tgenabled) ORDER BY c.relname,t.tgname),'[]'::jsonb) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid WHERE c.relnamespace='public'::regnamespace AND NOT t.tgisinternal),
 'functions',(SELECT COALESCE(jsonb_agg(jsonb_build_array(p.oid::regprocedure::text,pg_get_functiondef(p.oid)) ORDER BY p.oid::regprocedure::text),'[]'::jsonb) FROM pg_proc p WHERE p.pronamespace='public'::regnamespace AND p.prokind IN ('f','p')),
 'indexes',(SELECT COALESCE(jsonb_agg(jsonb_build_array(indexname,indexdef) ORDER BY indexname),'[]'::jsonb) FROM pg_indexes WHERE schemaname='public'),
 'columns',(SELECT COALESCE(jsonb_agg(jsonb_build_array(c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,pg_get_expr(d.adbin,d.adrelid)) ORDER BY c.relname,a.attnum),'[]'::jsonb) FROM pg_class c JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum WHERE c.relnamespace='public'::regnamespace AND c.relkind IN ('r','p')),
 'sequence_ownership',(SELECT COALESCE(jsonb_agg(jsonb_build_array(seq.relname,tab.relname,a.attname,d.deptype) ORDER BY seq.relname),'[]'::jsonb) FROM pg_class seq JOIN pg_depend d ON d.objid=seq.oid AND d.classid='pg_class'::regclass AND d.refclassid='pg_class'::regclass AND d.deptype IN ('a','i') JOIN pg_class tab ON tab.oid=d.refobjid JOIN pg_attribute a ON a.attrelid=tab.oid AND a.attnum=d.refobjsubid WHERE seq.relkind='S' AND seq.relnamespace='public'::regnamespace),
 'enums',(SELECT COALESCE(jsonb_agg(jsonb_build_array(t.typname,e.enumlabel,e.enumsortorder) ORDER BY t.typname,e.enumsortorder),'[]'::jsonb) FROM pg_type t JOIN pg_enum e ON e.enumtypid=t.oid WHERE t.typnamespace='public'::regnamespace),
 'views',(SELECT COALESCE(jsonb_agg(jsonb_build_array(viewname,definition) ORDER BY viewname),'[]'::jsonb) FROM pg_views WHERE schemaname='public'),
 'extensions',(SELECT jsonb_agg(jsonb_build_array(extname,extversion) ORDER BY extname) FROM pg_extension),
 'unvalidated_constraints',(SELECT count(*) FROM pg_constraint WHERE connamespace='public'::regnamespace AND NOT convalidated),
 'invalid_indexes',(SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid WHERE c.relnamespace='public'::regnamespace AND NOT i.indisvalid))"""
def compare_release_schema(source, restored, base_compare, fixture):
    """Add exact audited 0132/0139 PG16 deparse pairs, never normalize SQL."""
    from copy import deepcopy
    from hashlib import sha256

    pairs = [
        ('mono_checkbox_poll_state', 'ck_mono_checkbox_poll_state_mono_checkbox_poll_kind',
         "CHECK (kind::text = ANY (ARRAY['shop'::character varying, 'master'::character varying]::text[]))",
         "CHECK (kind::text = ANY (ARRAY['shop'::character varying::text, 'master'::character varying::text]))"),
        ('shop_ingress_admissions', 'ck_shop_ingress_admissions_action',
         "CHECK (action::text = ANY (ARRAY['otp_send'::character varying, 'otp_verify'::character varying, 'checkout'::character varying, 'feedback'::character varying, 'review'::character varying, 'profile'::character varying, 'search'::character varying, 'cart'::character varying]::text[]))",
         "CHECK (action::text = ANY (ARRAY['otp_send'::character varying::text, 'otp_verify'::character varying::text, 'checkout'::character varying::text, 'feedback'::character varying::text, 'review'::character varying::text, 'profile'::character varying::text, 'search'::character varying::text, 'cart'::character varying::text]))"),
    ]
    working = deepcopy(source)
    accepted = []
    for table, name, source_definition, restored_definition in pairs:
        old = [row for row in source.get('constraints', []) if row[:2] == [table, name]]
        new = [row for row in restored.get('constraints', []) if row[:2] == [table, name]]
        if len(old) > 1 or len(new) > 1:
            raise RuntimeError('Duplicate release constraint identity')
        if old != new:
            if (len(old) != 1 or len(new) != 1 or len(old[0]) != 7 or len(new[0]) != 7
                    or old[0][2] != 'c' or old[0][:3] + old[0][4:] != new[0][:3] + new[0][4:]
                    or old[0][3] != source_definition or new[0][3] != restored_definition):
                raise RuntimeError('Unrecognized release constraint difference')
            next(row for row in working['constraints'] if row[:2] == [table, name])[3] = restored_definition
            accepted.append(dict(kind='constraint', table=table, name=name,
                                 source_definition=source_definition, restored_definition=restored_definition,
                                 source_sha256=sha256(source_definition.encode()).hexdigest(),
                                 restored_sha256=sha256(restored_definition.encode()).hexdigest()))
    return base_compare(working, restored, fixture) + accepted


FINITE_COMPARISON = """
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('approved_restore', '/app/scripts/rehearse_shop_restore.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
fixture = json.loads(Path('/app/scripts/fixtures/shop_restore_pg16_canonicalization.json').read_text())
""" + inspect.getsource(compare_release_schema) + """
before, after = json.load(sys.stdin)
print(json.dumps(compare_release_schema(before, after, module.source_restore_schema_equivalence, fixture)))
"""


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


def archive_identity(path):
    with path.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(bytes=path.stat().st_size, sha256=checksum)


def strip_dump_guard(data):
    lines = data.splitlines(keepends=True)
    starts = [(i, line.split()[1]) for i, line in enumerate(lines) if re.fullmatch(rb'\\restrict [A-Za-z0-9]+', line.rstrip(b'\r\n'))]
    ends = [(i, line.split()[1]) for i, line in enumerate(lines) if re.fullmatch(rb'\\unrestrict [A-Za-z0-9]+', line.rstrip(b'\r\n'))]
    if not starts and not ends:
        return data
    last = max(i for i, line in enumerate(lines) if line.strip())
    if len(starts) != 1 or len(ends) != 1 or starts[0][0] > 10 or ends[0][0] != last or starts[0][1] != ends[0][1]:
        raise RuntimeError('Unexpected pg_dump guard structure')
    return b''.join(line for i, line in enumerate(lines) if i not in (starts[0][0], ends[0][0]))


def verify_raw_schema(before, after, accepted, old_constraints, new_constraints, old_indexes, new_indexes):
    """Only replace exact compact definitions already approved by the finite comparator."""
    lines = before.splitlines(keepends=True)
    for pair in accepted:
        kind = pair['kind']
        if kind == 'enum_internal_sort_keys':
            continue
        if kind == 'constraint':
            name = pair['name']
            label = name if re.fullmatch(r'[a-z_][a-z_0-9]*', name) else identifier(name)
            key = pair['table'] + ':' + name
            replacements = [(f'    CONSTRAINT {label} {old_constraints[key]}' + suffix,
                             f'    CONSTRAINT {label} {new_constraints[key]}' + suffix) for suffix in ('', ',')]
        elif kind == 'index':
            replacements = [(old_indexes[pair['name']] + ';', new_indexes[pair['name']] + ';')]
        else:
            raise RuntimeError('Unknown finite schema comparison category')
        matches = [(i, old.encode(), new.encode()) for i, line in enumerate(lines) for old, new in replacements
                   if line.rstrip(b'\r\n') == old.encode()]
        if len(matches) != 1:
            raise RuntimeError('Finite schema object did not match exactly one dump line')
        index, old, new = matches[0]
        lines[index] = new + lines[index][len(old):]
    if b''.join(lines) != after:
        raise RuntimeError('Unrecognized raw schema difference after finite object comparison')


def fingerprint_sql(tables):
    parts = []
    for table, columns in tables.items():
        projection = ",".join(map(identifier, columns))
        relation = 'public.' + identifier(table)
        label = "'" + table.replace("'", "''") + "'"
        parts.append(
            f"SELECT {label} AS name, count(*) AS rows, "
            "md5(coalesce(string_agg(md5(row_to_json(t)::text), '' "
            f"ORDER BY md5(row_to_json(t)::text)), '')) AS digest "
            f"FROM (SELECT {projection} FROM {relation}) t")
    return "SELECT coalesce(json_agg(s ORDER BY name),'[]') FROM (" + " UNION ALL ".join(parts) + ") s"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--previous", required=True)
    parser.add_argument("--postgres-image", required=True)
    parser.add_argument("--source-head", choices=SOURCE_HEADS, default=BASE)
    parser.add_argument("--english-input-dir", type=Path)
    parser.add_argument("--english-products-sha256")
    parser.add_argument("--english-categories-sha256")
    parser.add_argument("--content-input-dir", type=Path)
    parser.add_argument("--content-sha256")
    parser.add_argument("--confirm-production-copy", action="store_true", required=True)
    args = parser.parse_args()
    if (args.content_input_dir or args.content_sha256) and (
            not args.content_input_dir or args.content_sha256 != CONTENT_SHA256
            or args.source_head != '0137_shop_online_payment' or args.english_input_dir):
        parser.error('Content rehearsal requires the exact reviewed input and explicit source head 0137')
    english_arguments = (args.english_input_dir, args.english_products_sha256, args.english_categories_sha256)
    if any(english_arguments) and (not all(english_arguments) or args.source_head != '0134_shop_canonical_collation'):
        parser.error('English rehearsal requires all reviewed input arguments and explicit source head 0134')
    if args.english_input_dir and any(not re.fullmatch(r'[0-9a-f]{64}', value) for value in english_arguments[1:]):
        parser.error('English input checksums must be exact SHA-256 values')
    for image in (args.candidate, args.previous):
        if not re.fullmatch(r"ghcr\.io/mharnichev/sc-be/api@sha256:[0-9a-f]{64}", image):
            parser.error("Images must use immutable digests in the approved backend registry")
    if not re.fullmatch(r"postgres@sha256:[0-9a-f]{64}", args.postgres_image):
        parser.error("PostgreSQL must use its reviewed production image digest")
    os.umask(0o077)
    run = "shop-rehearsal-" + uuid.uuid4().hex
    output = Path("/opt/soulcuts/backups") / run
    output.mkdir(mode=0o700, parents=False)
    english_inputs = None
    english_hashes = None
    if args.english_input_dir:
        english_inputs, english_hashes = seal_english_inputs(args.english_input_dir,
            dict(products=args.english_products_sha256, categories=args.english_categories_sha256), output)
    elif args.content_input_dir:
        english_inputs, english_hashes = seal_english_inputs(args.content_input_dir,
            dict(products=args.content_sha256), output, definitions=CONTENT_INPUTS)
    network, postgres = run + "-net", run + "-pg"
    migration_task, compatibility_task = run + "-migration", run + "-compatibility"
    comparison_task = run + "-schema-comparison"
    english_tasks = [run+'-english-'+kind+'-'+phase for phase in ('dry-run','apply','idempotent')
                     for kind, _, _, _ in ENGLISH_INPUTS]
    log = (output / "commands.log").open("xb")

    def execute(command, *, data=None, target=None):
        result = subprocess.run(command, input=data, stdout=target or subprocess.PIPE, stderr=log, timeout=1200)
        if result.returncode:
            raise RuntimeError("Rehearsal command failed; inspect the private command log")
        return result.stdout

    def sql(database, query):
        return execute(["docker", "exec", "-i", postgres, "psql", "-X", "-v", "ON_ERROR_STOP=1",
                        "-U", "rehearsal", "-d", database, "-At"], data=query.encode()).decode().strip()

    def snapshot(database, tables):
        return json.loads(sql(database, fingerprint_sql(tables)))

    def sequences(database):
        names = json.loads(sql(database, "SELECT coalesce(json_agg(sequencename ORDER BY sequencename),'[]') FROM pg_sequences WHERE schemaname='public'"))
        return {name: sql(database, 'SELECT last_value,is_called FROM public.' + identifier(name)) for name in names}

    def dump(database, target, schema=False):
        command = ["docker", "exec", postgres, "pg_dump", "-U", "rehearsal", "-d", database,
                   "--no-owner", "--no-privileges"]
        command += ["--schema-only"] if schema else ["-Fc"]
        with target.open("xb") as stream:
            execute(command, target=stream)

    def restore(database, archive):
        # No production credentials, host networking, ports or provider secrets are supplied.
        with archive.open("rb") as stream:
            result = subprocess.run(["docker", "exec", "-i", postgres, "pg_restore", "-U", "rehearsal",
                                     "-d", database, "--exit-on-error", "--single-transaction", "--no-owner",
                                     "--no-privileges"], stdin=stream, stdout=log, stderr=log, timeout=1200)
        if result.returncode:
            raise RuntimeError("Private copy restore failed")

    archive = output / source_archive_name(args.source_head)
    try:
        size = int(execute(["docker", "exec", "soulcuts-postgres-1", "sh", "-ec",
                           'exec psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT pg_database_size(current_database())"']).strip())
        memory = {line.split(':')[0]: int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()}
        if size > 512 * 1024**2 or shutil.disk_usage(output).free < 8 * 1024**3 + 10 * size or memory['MemAvailable'] < 6 * 1024**3:
            raise RuntimeError("Insufficient bounded rehearsal headroom; no database copy attempted")
        with archive.open("xb") as stream:
            execute(["docker", "exec", "soulcuts-postgres-1", "sh", "-ec",
                     'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-privileges --lock-wait-timeout=5s'], target=stream)
        execute(["docker", "network", "create", "--internal", network])
    except BaseException:
        log.close()
        raise
    stopped = False
    try:
        execute(["docker", "run", "-d", "--name", postgres, "--network", network,
                 "--memory=2g", "--cpus=1", "--pids-limit=256",
                 "--tmpfs", "/var/lib/postgresql/data:rw,size=1536m,mode=0700",
                 "-e", "POSTGRES_USER=rehearsal", "-e", "POSTGRES_DB=upgrade_copy",
                 "-e", "POSTGRES_INITDB_ARGS=--locale=en_US.utf8",
                 "-e", "POSTGRES_HOST_AUTH_METHOD=trust", args.postgres_image])
        execute(["docker", "exec", postgres, "sh", "-ec",
                 'for i in $(seq 1 60); do pg_isready -h 127.0.0.1 -U rehearsal -d upgrade_copy && exit 0; sleep 1; done; exit 1'])
        restore("upgrade_copy", archive)
        source = verify_source_copy(sql, args.source_head)
        tables = json.loads(sql("upgrade_copy", """
            SELECT json_object_agg(table_name, columns) FROM (
              SELECT table_name, json_agg(column_name ORDER BY ordinal_position) AS columns
              FROM information_schema.columns WHERE table_schema='public' AND table_name <> 'alembic_version'
              AND table_name IN (SELECT tablename FROM pg_tables WHERE schemaname='public')
              GROUP BY table_name) s"""))
        before = snapshot("upgrade_copy", tables)
        before_sequences = sequences("upgrade_copy")
        env = output / "copy.env"
        env.write_text("\n".join([
            "APP_ENV=production", "DEBUG=false", "SECRET_KEY=" + secrets.token_hex(32),
            "CORS_ORIGINS=https://soulcuts.com.ua", "POSTGRES_HOST=" + postgres,
            "POSTGRES_DB=upgrade_copy", "POSTGRES_USER=rehearsal", "POSTGRES_PASSWORD=unused",
            "BACKGROUND_WORKERS_ENABLED=false", "SMS_QUEUE_WORKER_ENABLED=false",
            "CAMPAIGN_RUN_SCHEDULER_ENABLED=false", "SHOP_CHECKOUT_ENABLED=false",
            "PGOPTIONS=-c lock_timeout=5s -c statement_timeout=120s", ""]))
        execute(["docker", "run", "--rm", "--name", migration_task, "--network", network, "--env-file", str(env),
                 "--memory=768m", "--cpus=1", "--pids-limit=128", "--pull=never",
                 "--entrypoint", "alembic", args.candidate, "upgrade", "head"])
        if sql("upgrade_copy", "SELECT version_num FROM alembic_version") != HEAD:
            raise RuntimeError("Candidate copy did not reach the exact reviewed head")
        if before != snapshot("upgrade_copy", tables):
            raise RuntimeError("Existing production rows changed during the migration rehearsal")
        after_sequences = sequences("upgrade_copy")
        if any(after_sequences.get(name) != value for name, value in before_sequences.items()):
            raise RuntimeError("Existing production sequences changed during the migration rehearsal")
        english_result = None
        if english_inputs:
            english_result = rehearse_english(execute, sql, args.candidate, network, env, run,
                                               output, english_inputs, english_hashes,
                                               definitions=CONTENT_INPUTS if args.content_input_dir else ENGLISH_INPUTS)
            if before != snapshot('upgrade_copy', tables):
                raise RuntimeError('English backfill changed original production columns')
            if after_sequences != sequences('upgrade_copy'):
                raise RuntimeError('English backfill changed sequences')
            english_result['original_columns_unchanged'] = True
            english_result['sequences_unchanged'] = True
        upgraded_tables = json.loads(sql("upgrade_copy", """
            SELECT json_object_agg(table_name, columns) FROM (
              SELECT table_name, json_agg(column_name ORDER BY ordinal_position) AS columns
              FROM information_schema.columns WHERE table_schema='public'
              AND table_name IN (SELECT tablename FROM pg_tables WHERE schemaname='public')
              GROUP BY table_name) s"""))
        upgraded = snapshot("upgrade_copy", upgraded_tables)
        upgrade_archive = output / "upgraded-0139.dump"
        dump("upgrade_copy", upgrade_archive)
        sql("postgres", "CREATE DATABASE restore_copy OWNER rehearsal")
        restore("restore_copy", upgrade_archive)
        if upgraded != snapshot("restore_copy", upgraded_tables):
            raise RuntimeError("Upgraded copy restore changed row fingerprints")
        if after_sequences != sequences("restore_copy"):
            raise RuntimeError("Upgraded copy restore changed sequences")
        for database in ("upgrade_copy", "restore_copy"):
            dump(database, output / (database + "-schema.sql"), schema=True)
        # Only the paired top-level pg_dump SQL injection guards have random tokens.
        def schema(path):
            return strip_dump_guard(path.read_bytes())
        old_raw = schema(output / "upgrade_copy-schema.sql")
        new_raw = schema(output / "restore_copy-schema.sql")
        raw_schema_equal = old_raw == new_raw
        before_schema = json.loads(sql('upgrade_copy', SCHEMA_SQL))
        after_schema = json.loads(sql('restore_copy', SCHEMA_SQL))
        for value in (before_schema, after_schema):
            if value['unvalidated_constraints'] or value['invalid_indexes']:
                raise RuntimeError('Invalid restored constraints or indexes')
        accepted_pairs = json.loads(execute([
            'docker', 'run', '--rm', '-i', '--name', comparison_task, '--network', 'none',
            '--memory=768m', '--cpus=1', '--pids-limit=128', '--pull=never', '--entrypoint', 'python',
            args.candidate, '-c', FINITE_COMPARISON], data=json.dumps([before_schema, after_schema]).encode()))
        compact_sql = "SELECT coalesce(json_object_agg(conrelid::regclass::text || ':' || conname,pg_get_constraintdef(oid,false)),'{}') FROM pg_constraint WHERE connamespace='public'::regnamespace"
        verify_raw_schema(old_raw, new_raw, accepted_pairs,
                          json.loads(sql('upgrade_copy', compact_sql)), json.loads(sql('restore_copy', compact_sql)),
                          dict(before_schema['indexes']), dict(after_schema['indexes']))
        (output / 'schema-comparison.json').write_text(json.dumps(dict(
            source=before_schema, restored=after_schema, accepted_pairs=accepted_pairs), indent=2) + '\n')
        compatibility = """
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.customer import Customer
from app.models.product import Product
from app.models.admin_user import AdminUser
from app.models.booking import Booking
from app.models.order import Order
engine = create_engine(settings.sqlalchemy_sync_database_uri)
with engine.connect() as connection:
    connection.execute(text('SET TRANSACTION READ ONLY'))
    with Session(bind=connection) as session:
        for model in (Customer, Product, AdminUser, Booking, Order):
            session.scalars(select(model).limit(1)).first()
engine.dispose()
"""
        execute(["docker", "run", "--rm", "--name", compatibility_task, "--network", network, "--env-file", str(env),
                 "--memory=768m", "--cpus=1", "--pids-limit=128", "--pull=never",
                 "--entrypoint", "python", args.previous, "-c", compatibility])
        execute(["docker", "stop", postgres])
        if execute(["docker", "inspect", "--format", "{{.State.Running}}", postgres]).strip() != b'false':
            raise RuntimeError("Private production copy did not stop")
        stopped = True
        report = dict(candidate=args.candidate, previous=args.previous, postgres=args.postgres_image, **source, head=HEAD,
                      english_backfill=None if args.content_input_dir else english_result,
                      content_backfill=english_result if args.content_input_dir else None,
                      existing_rows_unchanged=True, existing_sequences_unchanged=True,
                      restored_rows_equal=True, restored_sequences_equal=True, restored_schema_equal_after_finite_contract=True,
                      raw_schema_equal=raw_schema_equal,
                      finite_schema_pairs=[{key: value[key] for key in ('kind', 'table', 'name') if key in value} for value in accepted_pairs],
                      source_tables=len(tables), upgraded_tables=len(upgraded_tables),
                      archives={p.name: archive_identity(p) for p in (archive, upgrade_archive)},
                      previous_image_compatibility="five core ORM models read-only passed; no automatic rollback is approved")
        (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(dict(result="passed", artifacts=str(output), head=HEAD)))
    finally:
        # tmpfs is discarded on stop. Retain only protected archives, never production objects.
        handlers = {number: signal.signal(number, signal.SIG_IGN) for number in (signal.SIGTERM, signal.SIGHUP)}
        try:
            if not stopped:
                try:
                    # Killing a docker CLI on timeout does not kill its container process.
                    for task in (migration_task, compatibility_task, comparison_task, *english_tasks):
                        result = subprocess.run(["docker", "ps", "-aq", "--filter", "name=^/" + task + "$"],
                                                stdout=subprocess.PIPE, stderr=log, timeout=30)
                        if result.returncode:
                            raise RuntimeError("CRITICAL: cannot verify rehearsal task cleanup")
                        if result.stdout.strip():
                            result = subprocess.run(["docker", "stop", "--time", "5", task], stdout=log, stderr=log, timeout=30)
                            if result.returncode:
                                raise RuntimeError("CRITICAL: rehearsal task stop failed")
                finally:
                    result = subprocess.run(["docker", "stop", "--time", "30", postgres], stdout=log, stderr=log, timeout=60)
                    if result.returncode:
                        raise RuntimeError("CRITICAL: private copy stop failed; inspect its container immediately")
        finally:
            log.close()
            for number, handler in handlers.items():
                signal.signal(number, handler)


if __name__ == "__main__":
    def interrupted(number, _frame):
        raise SystemExit(128 + number)

    for number in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    main()
