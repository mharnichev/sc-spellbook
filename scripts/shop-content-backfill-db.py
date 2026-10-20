#!/usr/bin/env python3
"""Content-only specialization of the existing snapshot and whole-vector CAS tool."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('content_db_engine', Path(__file__).with_name('english-backfill-db.py'))
DB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DB)
DB.HEAD = '0138_shop_content_en'
DB.FIELDS = {'products': ('description_en', 'short_description_en', 'ingredients_en')}
DB.CATALOG_COLUMNS = {**DB.CATALOG_COLUMNS, 'products': (
    'id', 'name', 'slug', 'product_type', 'description', 'short_description', 'ingredients')}
DB.ORIGINAL_KEYS = (*DB.ORIGINAL_KEYS, 'grants')
DB.LIVE_KEYS = (*DB.LIVE_KEYS, 'grants')
DB.ROLLBACK_LOCK_SQL = 'LOCK TABLE products IN SHARE ROW EXCLUSIVE MODE'
BASE_SNAPSHOT = DB.snapshot


def validate_targets(baseline, target):
    DB.require(set(target) == {'products'})
    rows = target['products']
    fields = DB.FIELDS['products']
    DB.require(isinstance(rows, list)
               and all(isinstance(row, dict) and set(row) == {'id', *fields}
                       and type(row['id']) is int and row['id'] > 0 for row in rows))
    DB.require(len({row['id'] for row in rows}) == len(rows)
               and [row['id'] for row in rows] == [row['id'] for row in baseline['english']['products']])
    DB.require(all(row[field] is None or isinstance(row[field], str)
                   and bool(row[field].strip()) for row in rows for field in fields))


def snapshot(connection, text):
    result = BASE_SNAPSHOT(connection, text)
    result['grants'] = connection.execute(text("""SELECT jsonb_build_object(
      'admins',(SELECT COALESCE(jsonb_agg((SELECT jsonb_object_agg(k,v)
        FROM jsonb_each(to_jsonb(a)) AS e(k,v) WHERE jsonb_typeof(v)='boolean' OR k='id')
        ORDER BY id),'[]') FROM admin_users a),
      'masters',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',id,
        'admin_user_id',admin_user_id,'is_active',is_active) ORDER BY id),'[]') FROM masters))""")).scalar_one()
    return result


DB.validate_targets = validate_targets
DB.snapshot = snapshot

if __name__ == '__main__':
    try:
        DB.main()
    except Exception:
        raise SystemExit('Content database operation failed closed; private values suppressed') from None
