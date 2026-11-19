"""Real upgrade paths for the typed audit repair; own PG55434 schemas only."""
import hashlib
import json
import os
from pathlib import Path
import unittest
from urllib.parse import urlsplit
from uuid import uuid4

from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = "(scope = 'accounts' AND target_id IS NULL AND target_account_id IS NOT NULL) OR (scope <> 'accounts' AND target_id IS NOT NULL AND target_account_id IS NULL)"
ORIGINAL_0047 = "(scope = 'accounts' AND target_id IS NULL AND target_account_id IS NOT NULL) OR (scope IN ('users','chats') AND target_id IS NOT NULL AND target_account_id IS NULL)"


@unittest.skipUnless(os.getenv('NIGHT_AUDIT_MIGRATION_TESTS') == '1', 'explicit NIGHT_AUDIT_MIGRATION_TESTS=1 required')
class AdminAuditScopeMigrationPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests.night_case_test_database import night_case_test_url
        url = night_case_test_url()
        parsed = urlsplit(url)
        if os.getenv('TEST_DATABASE_URL') != url or parsed.hostname not in {'127.0.0.1', 'localhost'} or parsed.port != 55434:
            raise RuntimeError('audit migration tests require matching TEST/NIGHT_CASE URL on owned PG55434')
        self.schema = 'mqb_audit_scope_' + uuid4().hex
        self.engine = create_async_engine(url, connect_args={'server_settings': {'search_path': self.schema}})
        self.addAsyncCleanup(self.cleanup)
        async with self.engine.begin() as conn:
            await conn.exec_driver_sql('CREATE SCHEMA "' + self.schema + '"')
        self.config = Config(str(ROOT / 'alembic.ini'))
        self.config.set_main_option('script_location', str(ROOT / 'alembic'))
        self.script = ScriptDirectory.from_config(self.config)

    async def cleanup(self):
        async with self.engine.begin() as conn:
            await conn.exec_driver_sql('DROP SCHEMA IF EXISTS "' + self.schema + '" CASCADE')
        await self.engine.dispose()

    async def migrate(self, revision, *, downgrade=False):
        def run(sync):
            fn = (lambda current, ctx: self.script._downgrade_revs(revision, current)) if downgrade else (
                lambda current, ctx: self.script._upgrade_revs(revision, current))
            with EnvironmentContext(self.config, self.script, fn=fn, destination_rev=revision) as env:
                env.configure(connection=sync, version_table_schema=self.schema)
                with env.begin_transaction():
                    env.run_migrations()
        async with self.engine.begin() as conn:
            await conn.run_sync(run)

    async def insert_audit(self, scope, target_id, *, account_id=None):
        values = {'id': str(uuid4()), 'scope': scope, 'target': target_id,
                  'request': json.dumps({'preserve': scope, 'n': target_id}), 'account': account_id,
                  'before': json.dumps({'before': True}), 'after': json.dumps({'after': 7})}
        async with self.engine.begin() as conn:
            columns = 'id,scope,target_id,kind,request,before,after'
            placeholders = ":id,:scope,:target,'legacy',CAST(:request AS json),CAST(:before AS json),CAST(:after AS json)"
            if account_id is not None:
                columns += ',target_account_id'
                placeholders += ',:account'
            await conn.execute(text('INSERT INTO admin_actions (' + columns + ') VALUES (' + placeholders + ')'), values)

    async def fingerprints(self):
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text('SELECT id,to_jsonb(a) FROM admin_actions a ORDER BY id'))).all()
            result = {}
            for key, row in rows:
                # A new NULL column is the sole permitted shape change for0044.
                # Existing UUID targets remain part of full-row fingerprints.
                if row.get('target_account_id') is None:
                    row.pop('target_account_id', None)
                result[key] = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            return result

    async def version(self):
        async with self.engine.connect() as conn:
            return await conn.scalar(text('SELECT version_num FROM alembic_version'))

    async def account(self):
        account_id = uuid4()
        async with self.engine.begin() as conn:
            await conn.execute(text("INSERT INTO accounts (id,display_name) VALUES (:id,'Synthetic audit account')"), {'id': account_id})
        return account_id

    async def assert_target_matrix(self):
        account_id = await self.account()
        for scope in ('system', 'broadcast', 'categories', 'farm_upkeep', 'users', 'chats', 'future_scope'):
            await self.insert_audit(scope, 0)
            for target, account in ((None, None), (0, account_id), (None, account_id)):
                with self.assertRaises(DBAPIError):
                    await self.insert_audit(scope, target, account_id=account)
        await self.insert_audit('accounts', None, account_id=account_id)
        for target, account in ((0, None), (None, None), (0, account_id)):
            with self.assertRaises(DBAPIError):
                await self.insert_audit('accounts', target, account_id=account)

    async def test_0044_legacy_receipts_survive_repaired_0046_through_0048(self):
        await self.migrate('20261030_0044')
        for scope in ('system', 'broadcast', 'categories', 'farm_upkeep', 'users', 'chats'):
            await self.insert_audit(scope, 0)
            await self.insert_audit(scope, -44)
        before = await self.fingerprints()
        self.assertEqual(len(before), 12)
        await self.migrate('20261116_0048')
        self.assertEqual(await self.version(), '20261116_0048')
        self.assertEqual(await self.fingerprints(), before)
        await self.assert_target_matrix()
        async with self.engine.connect() as conn:
            self.assertFalse(await conn.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname=:schema AND tablename LIKE 'night_ai_%')"), {'schema': self.schema}))

    async def test_existing_0047_original_check_is_repaired_and_downgrade_keeps_fix(self):
        await self.migrate('20261116_0047')
        async with self.engine.begin() as conn:
            await conn.exec_driver_sql('ALTER TABLE admin_actions DROP CONSTRAINT ck_admin_actions_typed_target')
            await conn.exec_driver_sql('ALTER TABLE admin_actions ADD CONSTRAINT ck_admin_actions_typed_target CHECK (' + ORIGINAL_0047 + ')')
        await self.insert_audit('users', 0)
        await self.insert_audit('chats', -100)
        account_id = await self.account()
        await self.insert_audit('accounts', None, account_id=account_id)
        before = await self.fingerprints()
        with self.assertRaises(DBAPIError):
            await self.insert_audit('system', 0)  # Real RED with the original0047 CHECK.
        await self.migrate('20261116_0048')
        self.assertEqual(await self.fingerprints(), before)
        await self.assert_target_matrix()
        retained = await self.fingerprints()
        await self.migrate('20261116_0047', downgrade=True)
        self.assertEqual(await self.version(), '20261116_0047')
        self.assertEqual(await self.fingerprints(), retained)
        await self.insert_audit('farm_upkeep', 0)

    async def test_legacy_accounts_integer_namespace_fails_before_rewrite(self):
        await self.migrate('20261030_0044')
        await self.insert_audit('accounts', 0)
        before = await self.fingerprints()
        with self.assertRaisesRegex(DBAPIError, 'typed_audit_legacy_accounts_conflict'):
            await self.migrate('20261116_0048')
        self.assertEqual(await self.version(), '20261030_0044')
        self.assertEqual(await self.fingerprints(), before)
        async with self.engine.connect() as conn:
            count = await conn.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema=:schema AND table_name='admin_actions' AND column_name='target_account_id'"), {'schema': self.schema})
            self.assertEqual(count, 0)
