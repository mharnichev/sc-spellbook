import importlib.util
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1]/'scripts/english-backfill-network-guard.py'
SPEC = importlib.util.spec_from_file_location('english_network_guard',SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EnglishNetworkGuardTests(unittest.TestCase):
    @contextmanager
    def invocation(self, *, overrides=None, environment=None, args=None):
        # Mock external configuration/parser boundaries, not the guard decisions.
        url = Mock()
        for key, value in dict(drivername='postgresql+asyncpg', host='postgres',
                               port=None, database='barbershop_platform', query={}).items():
            setattr(url, key, value)
        for key, value in (overrides or {}).items():
            setattr(url, key, value)
        url.set.return_value.render_as_string.return_value = 'normalized-loopback-url'
        settings = SimpleNamespace(sqlalchemy_database_uri='private-input',
                                   app_env='production', database_url='original')
        engine = ModuleType('sqlalchemy.engine')
        engine.make_url = Mock(return_value=url)
        config = ModuleType('app.core.config')
        config.settings = settings
        modules = {'sqlalchemy': ModuleType('sqlalchemy'), 'sqlalchemy.engine': engine,
                   'app': ModuleType('app'), 'app.core': ModuleType('app.core'),
                   'app.core.config': config}
        with patch.dict(sys.modules, modules), \
             patch.dict(os.environ, environment or {}, clear=True), \
             patch.object(sys, 'argv', ['guard', *(args or [
                 '-m', 'app.utils.backfill_product_names_en', '--dry-run'])]), \
             patch.object(socket.socket, 'connect') as connect, \
             patch.object(socket.socket, 'connect_ex') as connect_ex, \
             patch.object(MODULE.runpy, 'run_module') as run_module, \
             patch.object(MODULE.runpy, 'run_path') as run_path:
            yield SimpleNamespace(url=url, settings=settings, connect=connect,
                                  connect_ex=connect_ex, run_module=run_module,
                                  run_path=run_path, make_url=engine.make_url)

    def assert_refused(self, **kwargs):
        with self.invocation(**kwargs) as state:
            with self.assertRaises(RuntimeError):
                MODULE.main()
            state.run_module.assert_not_called()
            state.run_path.assert_not_called()
            state.connect.assert_not_called()
            state.connect_ex.assert_not_called()
            state.url.set.assert_not_called()
            self.assertEqual(state.settings.database_url, 'original')

    def test_unreviewed_drivers_refused_before_tool_execution(self):
        for driver in ('postgresql', 'postgresql+psycopg', 'postgresql+pg8000',
                       'mysql+pymysql', 'sqlite'):
            with self.subTest(driver=driver):
                self.assert_refused(overrides={'drivername': driver})

    def test_all_query_parameters_refused_for_both_drivers(self):
        for driver in ('postgresql+asyncpg', 'postgresql+psycopg2'):
            for key, value in (('host', 'foreign'), ('hostaddr', '192.0.2.1'),
                               ('port', '6543'), ('service', 'foreign'),
                               ('servicefile', '/tmp/foreign'), ('sslmode', 'require'),
                               ('host', '')):
                with self.subTest(driver=driver, query=key, value=value):
                    self.assert_refused(overrides={'drivername': driver,
                                                  'query': {key: value}})

    def test_libpq_environment_routes_refused_for_both_drivers(self):
        for driver in ('postgresql+asyncpg', 'postgresql+psycopg2'):
            for key in ('PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE'):
                for value in ('foreign', ' '):
                    with self.subTest(driver=driver, variable=key, value=value):
                        self.assert_refused(overrides={'drivername': driver},
                                            environment={key: value})

    def test_foreign_authority_and_production_database_refused(self):
        for overrides in ({'host': 'foreign'}, {'host': '/tmp'}, {'host': None},
                          {'port': 6543}, {'database': 'other'}):
            with self.subTest(overrides=overrides):
                self.assert_refused(overrides=overrides)

    def test_reviewed_drivers_normalize_before_each_allowed_tool(self):
        tools = (['-m', 'app.utils.backfill_product_names_en', '--dry-run'],
                 ['-m', 'app.utils.backfill_category_names_en', '--dry-run'],
                 ['-m', 'app.utils.backfill_shop_content_en', '--dry-run'],
                 ['/release-tools/scripts/shop-content-backfill-db.py', 'verify'],
                 ['/release-tools/scripts/english-backfill-db.py', 'verify'])
        for driver in ('postgresql+asyncpg', 'postgresql+psycopg2'):
            for host in ('postgres', '127.0.0.1', '::1'):
                for args in tools:
                    with self.subTest(driver=driver, host=host, tool=args[0:2]), \
                         self.invocation(overrides={'drivername': driver, 'host': host},
                                         environment={'PGHOSTADDR': '', 'PGSERVICE': '',
                                                      'PGSERVICEFILE': ''}, args=args) as state:
                        MODULE.main()
                        state.url.set.assert_called_once_with(host='127.0.0.1', port=5432)
                        self.assertEqual(state.settings.database_url, 'normalized-loopback-url')
                        if args[0] == '-m':
                            state.run_module.assert_called_once_with(args[1], run_name='__main__')
                            state.run_path.assert_not_called()
                        else:
                            state.run_path.assert_called_once_with(args[0], run_name='__main__')
                            state.run_module.assert_not_called()
                        state.connect.assert_not_called()
                        state.connect_ex.assert_not_called()

    def test_unreviewed_tool_refused_before_configuration_import(self):
        with self.invocation(args=['-m', 'app.main']) as state:
            with self.assertRaisesRegex(RuntimeError, 'Unreviewed database tool'):
                MODULE.main()
            state.make_url.assert_not_called()
            state.run_module.assert_not_called()
            state.run_path.assert_not_called()

    def test_content_entrypoints_preserve_all_route_refusals(self):
        for args in (['-m', 'app.utils.backfill_shop_content_en', '--apply'],
                     ['/release-tools/scripts/shop-content-backfill-db.py', 'rollback']):
            for overrides in ({'drivername': 'postgresql+psycopg'},
                              {'host': 'foreign'}, {'port': 6543},
                              {'query': {'hostaddr': '192.0.2.1'}},
                              {'query': {'service': 'foreign'}}):
                with self.subTest(args=args, overrides=overrides):
                    self.assert_refused(args=args, overrides=overrides)
            for key in ('PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE'):
                with self.subTest(args=args, variable=key):
                    self.assert_refused(args=args, environment={key: 'foreign'})

    def test_content_near_misses_refuse_before_configuration(self):
        for args in (['-m', 'app.utils.backfill_shop_content_en.extra'],
                     ['/release-tools/scripts/../scripts/shop-content-backfill-db.py'],
                     ['/tmp/shop-content-backfill-db.py']):
            with self.subTest(args=args), self.invocation(args=args) as state:
                with self.assertRaisesRegex(RuntimeError, 'Unreviewed database tool'):
                    MODULE.main()
                state.make_url.assert_not_called()
                state.run_module.assert_not_called()
                state.run_path.assert_not_called()

    def test_only_postgres_loopback_reaches_native_python_connect(self):
        with patch.object(socket.socket,'connect',return_value=None) as native, \
             patch.object(socket.socket,'connect_ex',return_value=0) as native_ex:
            MODULE.restrict_python_sockets()
            with socket.socket() as sock:
                sock.connect(('127.0.0.1',5432))
                self.assertEqual(sock.connect_ex(('127.0.0.1',5432)),0)
                for address in (('api.monobank.ua',443),('127.0.0.1',80),('172.18.0.2',5432),'unix.sock'):
                    with self.subTest(address=address), self.assertRaises(RuntimeError):
                        sock.connect(address)
                    with self.assertRaises(RuntimeError):
                        sock.connect_ex(address)
            native.assert_called_once()
            native_ex.assert_called_once()
