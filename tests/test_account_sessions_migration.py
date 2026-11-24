"""PostgreSQL round trip for legacy browser and Mini App sessions."""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from storage.models import Account, User
from tests.local_database import isolated_database
from tests.test_postgres_members import pg_env


def test_account_sessions_upgrade_and_downgrade_keep_all_rows(pg_env):
    scripts = ScriptDirectory.from_config(Config('alembic.ini'))
    migration = scripts.get_revision('20261124_0051').module
    old_mini = scripts.get_revision('20260830_0006').module

    async def run():
        async with isolated_database(pg_env) as (database, schema):
            account_id, user_id = uuid4(), 981000000051
            async with database.transaction() as session:
                session.add(Account(id=account_id, display_name='Migration account'))
                await session.flush()
                session.add(User(id=user_id, account_id=account_id, display_name='Migration user'))

            async with database.engine.begin() as connection:
                await connection.run_sync(lambda sync: round_trip(sync, schema, account_id, user_id))

    def round_trip(connection, schema, account_id, user_id):
        # The fixture starts with the checked-out ORM. Recreate only the two
        # legacy tables in its private schema before populating them.
        for name in ('account_sessions', 'guest_sessions', 'mini_app_sessions'):
            connection.exec_driver_sql(f'DROP TABLE IF EXISTS "{schema}"."{name}"')
        connection.exec_driver_sql("""
            CREATE TABLE guest_sessions (
                token_hash VARCHAR(64) PRIMARY KEY,
                account_id UUID NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
                account_revision INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                revoked BOOLEAN NOT NULL DEFAULT false,
                created_via VARCHAR(16),
                user_agent VARCHAR(120)
            )
        """)
        connection.exec_driver_sql('CREATE INDEX ix_guest_sessions_account_id ON guest_sessions (account_id)')
        connection.exec_driver_sql('CREATE INDEX ix_guest_sessions_expires_at ON guest_sessions (expires_at)')
        with Operations.context(MigrationContext.configure(connection)):
            old_mini.upgrade()

        now = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
        shared_hash = 'a' * 64
        guest_insert = text("""
            INSERT INTO guest_sessions
                (token_hash, account_id, account_revision, created_at, expires_at, revoked, created_via, user_agent)
            VALUES (:token_hash, :account_id, :account_revision, :created_at, :expires_at, :revoked, :created_via, :user_agent)
        """)
        shared_browser = dict(token_hash=shared_hash, account_id=account_id, account_revision=4,
                              created_at=now, expires_at=now + timedelta(days=30), revoked=False,
                              created_via='telegram', user_agent='Browser migration test')
        null_browser = dict(shared_browser, token_hash='b' * 64, expires_at=now - timedelta(seconds=1),
                            revoked=True, created_via=None, user_agent=None)
        connection.execute(guest_insert, [shared_browser, null_browser])
        mini_insert = text("""
            INSERT INTO mini_app_sessions
                (token_hash, bot_key_id, init_data_hash, user_id, user_revision, auth_date, created_at, expires_at, revoked)
            VALUES (:token_hash, :bot_key_id, :init_data_hash, :user_id, :user_revision, :auth_date, :created_at, :expires_at, :revoked)
        """)
        mini = dict(token_hash=shared_hash, bot_key_id='c' * 64, init_data_hash='d' * 64,
                    user_id=user_id, user_revision=7, auth_date=now - timedelta(minutes=2), created_at=now,
                    expires_at=now + timedelta(minutes=12), revoked=True)
        connection.execute(mini_insert, mini)

        def rows(name):
            return [dict(row) for row in connection.execute(text(f'SELECT * FROM {name} ORDER BY token_hash')).mappings()]

        browser_before, mini_before = rows('guest_sessions'), rows('mini_app_sessions')
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        def exists(name):
            return connection.scalar(text('SELECT to_regclass(:name)'), {'name': f'{schema}.{name}'}) is not None

        assert not exists('guest_sessions')
        assert not exists('mini_app_sessions')
        unified = rows('account_sessions')
        for kind, expected in (('browser', browser_before), ('mini', mini_before)):
            selected = [{key: row[key] for key in expected[0]} for row in unified if row['kind'] == kind]
            assert selected == expected

        # The revoked row still reserves its initData fingerprint for that bot.
        insert_mini = text("""
            INSERT INTO account_sessions
                (kind, token_hash, bot_key_id, init_data_hash, user_id, user_revision, auth_date, created_at, expires_at, revoked)
            VALUES ('mini', :token_hash, :bot_key_id, :init_data_hash, :user_id, :user_revision, :auth_date, :created_at, :expires_at, :revoked)
        """)
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(insert_mini, dict(mini, token_hash='e' * 64, revoked=False))
        other_bot = dict(mini, token_hash='f' * 64, bot_key_id='g' * 64, revoked=False)
        connection.execute(insert_mini, other_bot)
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(text("""
                INSERT INTO account_sessions (kind, token_hash, created_at, expires_at)
                VALUES ('mini', 'invalid-shape', now(), now())
            """))
        connection.execute(text("""
            UPDATE account_sessions SET revoked = true WHERE kind = 'browser' AND token_hash = :token
        """), {'token': shared_hash})
        browser_before[0]['revoked'] = True

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert not exists('account_sessions')
        assert rows('guest_sessions') == browser_before
        assert rows('mini_app_sessions') == [*mini_before, other_bot]
        inspector = inspect(connection)
        assert {row['name'] for row in inspector.get_indexes('guest_sessions', schema=schema)} == {
            'ix_guest_sessions_account_id', 'ix_guest_sessions_expires_at',
        }
        assert {row['name'] for row in inspector.get_indexes('mini_app_sessions', schema=schema)
                if not row.get('duplicates_constraint')} == {
            'ix_mini_app_sessions_user_expiry', 'ix_mini_app_sessions_expiry',
        }
        assert {row['name'] for row in inspector.get_unique_constraints('mini_app_sessions', schema=schema)} == {
            'uq_mini_app_init_data',
        }

    asyncio.run(run())
