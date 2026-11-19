"""0049 retention checks. PostgreSQL scenarios require separate explicit opt-in.

No public schema reset: each PG scenario owns a temporary synthetic schema. These
tests must not run while another task reserves the owned PG55434 database.
"""
import importlib.util
import io
import os
from pathlib import Path
import unittest
from urllib.parse import urlsplit
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from storage.database import Database, DatabaseSettings
from storage.models import Base
from storage.night_ai_models import AI_MODELS


def migration():
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/20261116_0049_night_ai_access.py'
    spec = importlib.util.spec_from_file_location('night_ai_retention_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_downgrade_locks_and_checks_every_table_before_first_drop():
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name='postgresql', opts={'as_sql': True, 'output_buffer': output})
    with Operations.context(context):
        migration().downgrade()
    sql = output.getvalue()
    before_drop, _ = sql.split('DROP TABLE', 1)
    lock, preflight = before_drop.split('DO $$', 1)
    assert 'ACCESS EXCLUSIVE MODE' in lock
    assert 'night_ai_retention_required' in preflight
    for model in AI_MODELS:
        assert model.__tablename__ in lock
        assert 'EXISTS (SELECT 1 FROM ' + model.__tablename__ + ')' in preflight
    assert sql.count('DROP TABLE') == 9


@unittest.skipUnless(os.getenv('NIGHT_AI_MIGRATION_TESTS') == '1', 'explicit NIGHT_AI_MIGRATION_TESTS=1 required')
class NightAIMigrationPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests.night_case_test_database import night_case_test_url
        url = night_case_test_url()
        parsed = urlsplit(url)
        if (os.getenv('TEST_DATABASE_URL') != url or parsed.hostname not in {'127.0.0.1', 'localhost'}
                or parsed.port != 55434):
            raise RuntimeError('AI migration tests require matching TEST/NIGHT_CASE URL on owned PG55434')
        self.schema = 'mqb_night_ai_' + uuid4().hex
        self.db = Database(DatabaseSettings(url=url))
        async with self.db.engine.begin() as conn:
            await conn.exec_driver_sql('CREATE SCHEMA "' + self.schema + '"')
        await self.db.engine.dispose()
        self.db.engine = create_async_engine(url, connect_args={'server_settings': {'search_path': self.schema + ',public'}})
        async with self.db.engine.begin() as conn:
            non_ai = [t for t in Base.metadata.sorted_tables if not t.name.startswith('night_ai_')]
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=non_ai))
        await self.apply('upgrade')

    async def asyncTearDown(self):
        async with self.db.engine.begin() as conn:
            await conn.exec_driver_sql('DROP SCHEMA "' + self.schema + '" CASCADE')
        await self.db.engine.dispose()

    async def apply(self, direction):
        def run(sync):
            with Operations.context(MigrationContext.configure(sync)):
                getattr(migration(), direction)()
        async with self.db.engine.begin() as conn:
            await conn.run_sync(run)

    async def ai_tables(self):
        async with self.db.engine.connect() as conn:
            return set((await conn.execute(text('SELECT tablename FROM pg_tables WHERE schemaname=:schema'),
                                           {'schema': self.schema})).scalars()) & {m.__tablename__ for m in AI_MODELS}

    async def test_empty_downgrade_and_upgrade_succeeds(self):
        self.assertEqual(len(await self.ai_tables()), 9)
        await self.apply('downgrade')
        self.assertEqual(await self.ai_tables(), set())
        await self.apply('upgrade')
        self.assertEqual(len(await self.ai_tables()), 9)

    async def test_populated_downgrade_refuses_before_any_drop_atomically(self):
        # A single receipt, without any credential/profile, is retained history.
        # Do not rely on row DELETE triggers: DROP bypasses those triggers.
        async with self.db.engine.begin() as conn:
            await conn.execute(text("""INSERT INTO night_ai_operations
                (principal_subject,client_request_id,operation,target_id,fingerprint,fingerprint_version,safe_result)
                VALUES ('admin:test:operator','retained-request','test','test',:hash,'sha256:1','{}')"""), {'hash': 'a' * 64})
        with self.assertRaisesRegex(DBAPIError, 'night_ai_retention_required'):
            await self.apply('downgrade')
        self.assertEqual(len(await self.ai_tables()), 9)
        async with self.db.engine.connect() as conn:
            self.assertEqual(await conn.scalar(text('SELECT count(*) FROM night_ai_operations')), 1)
            self.assertEqual(await conn.scalar(text("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=:schema AND p.proname IN ('night_ai_guard','night_ai_cross_guard')"), {'schema': self.schema}), 2)
