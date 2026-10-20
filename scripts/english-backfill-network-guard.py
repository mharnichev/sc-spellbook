#!/usr/bin/env python3
"""Run only the approved DB tools in the PostgreSQL container's network namespace."""
import runpy
import os
import socket
import sys


def restrict_python_sockets():
    def wrap(native):
        def guarded(sock, address):
            if not (isinstance(address, tuple) and len(address) >= 2
                    and address[0] in ('127.0.0.1','::1') and address[1] == 5432):
                raise RuntimeError('Only fixture/production PostgreSQL loopback is permitted')
            return native(sock, address)
        return guarded
    socket.socket.connect = wrap(socket.socket.connect)
    socket.socket.connect_ex = wrap(socket.socket.connect_ex)


def main():
    if sys.flags.optimize:
        raise RuntimeError('Optimized execution is forbidden')
    args = sys.argv[1:]
    modules = ('app.utils.backfill_product_names_en','app.utils.backfill_category_names_en')
    module = len(args) >= 2 and args[0] == '-m' and args[1] in modules
    script = bool(args) and args[0] == '/release-tools/scripts/english-backfill-db.py'
    if not (module or script):
        raise RuntimeError('Unreviewed database tool')
    restrict_python_sockets()
    from sqlalchemy.engine import make_url
    from app.core.config import settings
    url = make_url(settings.sqlalchemy_database_uri)
    if url.drivername not in ('postgresql+asyncpg', 'postgresql+psycopg2') or url.query:
        raise RuntimeError('Unexpected database driver or query parameters')
    if any(os.environ.get(key) for key in ('PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE')):
        raise RuntimeError('Unexpected PostgreSQL routing override')
    if url.host not in ('postgres','127.0.0.1','::1') or url.port not in (None,5432):
        raise RuntimeError('Unexpected database authority')
    if settings.app_env == 'production' and url.database != 'barbershop_platform':
        raise RuntimeError('Unexpected production database')
    # Only this short-lived process is changed; production env files are untouched.
    settings.database_url = url.set(host='127.0.0.1',port=5432).render_as_string(hide_password=False)
    if module:
        sys.argv = [args[1],*args[2:]]
        runpy.run_module(args[1],run_name='__main__')
    else:
        sys.argv = args
        runpy.run_path(args[0],run_name='__main__')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('English DB-only tool failed closed; private configuration suppressed') from None
