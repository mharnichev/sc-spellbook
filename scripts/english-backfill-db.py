#!/usr/bin/env python3
"""Bound DB operations for the release operator; no application lifespan or HTTP."""
import json
import sys

HEAD = '0136_category_names_en'
FIELDS = {'products': ('name_en', 'product_type_en'), 'categories': ('name_en',)}
CATALOG_COLUMNS = {'products': ('id', 'name', 'slug', 'product_type'),
                   'categories': ('id', 'name', 'slug', 'parent_id')}
ORIGINAL_KEYS = ('head', 'database_identity', 'inventory', 'fingerprints', 'sequences', 'catalog')
LIVE_KEYS = ('database_identity', 'catalog')
ROLLBACK_LOCK_SQL = 'LOCK TABLE categories, products IN SHARE ROW EXCLUSIVE MODE'


def require(value, message='English database safety condition failed'):
    if not value:
        raise RuntimeError(message)


def validate_targets(baseline, target):
    require(set(target) == set(FIELDS))
    for table, fields in FIELDS.items():
        rows = target[table]
        require(isinstance(rows, list))
        require(all(set(row) == {'id', *fields} and type(row['id']) is int for row in rows))
        require(len({row['id'] for row in rows}) == len(rows))
        require([row['id'] for row in rows] == [row['id'] for row in baseline['english'][table]])
        require(all(isinstance(row[field], str) and row[field] == row[field].strip()
                    and 2 <= len(row[field]) <= 255 for row in rows for field in fields))


def verify_original(current, baseline):
    for key in ORIGINAL_KEYS:
        require(current[key] == baseline[key], 'Original database provenance changed: '+key)


def snapshot(connection, text):
    require(connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == HEAD)
    database_identity = dict(connection.execute(text("""SELECT current_database() AS database,
        current_user AS role, current_setting('server_version_num') AS version,
        inet_server_addr()::text AS address, inet_server_port() AS port""")).mappings().one())
    preparer = connection.dialect.identifier_preparer
    inventory = connection.execute(text("""SELECT table_name, array_agg(column_name ORDER BY ordinal_position) AS columns
        FROM information_schema.columns WHERE table_schema='public'
        AND table_name IN (SELECT tablename FROM pg_tables WHERE schemaname='public')
        GROUP BY table_name ORDER BY table_name""")).mappings().all()
    inventory = [dict(row) for row in inventory]
    fingerprints = {}
    for entry in inventory:
        table = entry['table_name']
        row = 'to_jsonb(t)'
        if table in FIELDS:
            row += ' - ARRAY[' + ','.join("'"+field+"'" for field in FIELDS[table]) + ']'
        checksum = "encode(sha256(convert_to(("+row+")::text,'UTF8')),'hex')"
        query = ("SELECT count(*) AS rows, encode(sha256(convert_to(coalesce(string_agg("+checksum+
                 ",'' ORDER BY "+checksum+"),''),'UTF8')),'hex') AS sha256 FROM public."+
                 preparer.quote_identifier(table)+' t')
        fingerprints[table] = dict(connection.execute(text(query)).mappings().one())
    sequences = {}
    names = connection.execute(text("SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename")).scalars()
    for name in names:
        sequences[name] = dict(connection.execute(text('SELECT last_value,is_called FROM public.'+
                                                       preparer.quote_identifier(name))).mappings().one())
    catalog = {table: [dict(row) for row in connection.execute(
        text('SELECT '+','.join(columns)+' FROM '+table+' ORDER BY id')).mappings()]
        for table, columns in CATALOG_COLUMNS.items()}
    english = {table:[dict(row) for row in connection.execute(text('SELECT id,'+','.join(fields)+' FROM '+table+' ORDER BY id')).mappings()]
               for table, fields in FIELDS.items()}
    return dict(head=HEAD, database_identity=database_identity, inventory=inventory, fingerprints=fingerprints, sequences=sequences,
                catalog=catalog, english=english)


def operate(connection, text, mode, payload, expected_database=None):
    if mode != 'rollback':
        connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
    connection.execute(text("SET LOCAL lock_timeout='5s'"))
    connection.execute(text("SET LOCAL statement_timeout='30s'"))
    if expected_database is not None:
        require(connection.execute(text('SELECT current_database()')).scalar_one() == expected_database,
                'Wrong production database')
    if mode == 'rollback':
        # Deterministic lock order; all source and whole-vector CAS checks precede writes.
        connection.execute(text(ROLLBACK_LOCK_SQL))
    current = snapshot(connection, text)
    if mode == 'snapshot':
        return current
    baseline, target = payload['baseline'], payload['target']
    validate_targets(baseline, target)
    if mode in ('verify', 'rollback'):
        verify_original(current, baseline)
    elif mode == 'verify-live':
        for key in LIVE_KEYS:
            message = {'database_identity': 'Database identity changed',
                       'catalog': 'Catalog source identity changed'}.get(key, 'Live database provenance changed: '+key)
            require(current[key] == baseline[key], message)
    else:
        raise RuntimeError('Unrecognized database operation')
    if mode != 'rollback':
        require(current['english'] == target, 'English coverage differs from the reviewed target')
        return dict(verified=True, head=HEAD, **{table: len(rows) for table, rows in target.items()})
    for table in FIELDS:
        require(current['english'][table] in (baseline['english'][table], target[table]),
                'English entity has a mixed or foreign outcome: '+table)
    for table, fields in FIELDS.items():
        definitions = ','.join(['id integer', *(field+' text' for field in fields)])
        assignments = ','.join(field+'=x.'+field for field in fields)
        old = ','.join('p.'+field for field in fields)
        new = ','.join('x.'+field for field in fields)
        query = ('UPDATE '+table+' p SET '+assignments+
                 ' FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS x('+definitions+')'
                 ' WHERE p.id=x.id AND ROW('+old+') IS DISTINCT FROM ROW('+new+')')
        connection.execute(text(query), {'rows':json.dumps(baseline['english'][table])})
    after = snapshot(connection, text)
    verify_original(after, baseline)
    require(after['english'] == baseline['english'], 'English rollback did not restore the exact baseline')
    return dict(rolled_back=True, head=HEAD, original_columns_unchanged=True)


def main():
    require(not sys.flags.optimize, 'Optimized execution is forbidden')
    require(len(sys.argv) == 2 and sys.argv[1] in ('snapshot', 'verify', 'verify-live', 'rollback'))
    from sqlalchemy import create_engine, text
    from app.core.config import settings
    engine = create_engine(settings.sqlalchemy_sync_database_uri, connect_args={'connect_timeout':5})
    try:
        payload = {} if sys.argv[1] == 'snapshot' else json.load(sys.stdin)
        with engine.begin() as connection:
            result = operate(connection, text, sys.argv[1], payload,
                             expected_database='barbershop_platform' if settings.app_env == 'production' else None)
        print(json.dumps(result))
    finally:
        engine.dispose()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('English database operation failed closed; private values suppressed') from None
