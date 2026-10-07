"""Guest auth acceptance: isolated disposable PG schemas and HTTP boundaries."""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import func, select, text

from storage.database import normalize_database_url
from storage.guest_accounts import GuestAccounts, credential_hash, SESSION_SECONDS
from storage.mini_app import MiniAppError
from storage.models import Account, GuestSession, User
from tests.local_database import isolated_database
from web.mini_app import MiniAppSettings, create_app

ORIGIN = 'http://127.0.0.1:4185'
HEADERS = {'Origin': ORIGIN, 'X-Guest-CSRF': '1'}


@pytest.fixture
def guest_pg_url():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL is not configured; no production fallback')
    return normalize_database_url(url)


def test_guest_lifecycle_and_moderation(guest_pg_url):
    async def run():
        async with isolated_database(guest_pg_url) as (db, _):
            now = [1788120000]
            store = GuestAccounts(db, clock=lambda: now[0])
            profile, raw = await store.start()
            repeat, token = await store.start(raw)
            assert repeat == profile and token is None
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(Account)) == 1
                assert await session.scalar(select(func.count()).select_from(User)) == 0
                row = await session.get(GuestSession, credential_hash(raw))
                assert row.token_hash != raw and row.account_id is not None
            rotated, new_raw = await store.resume(raw)
            assert rotated['account_id'] == profile['account_id'] and new_raw == raw
            assert (await store.profile(raw))['account_id'] == profile['account_id']
            await store.logout(new_raw)
            with pytest.raises(MiniAppError):
                await store.profile(new_raw)
            _, raw = await store.start()
            now[0] += SESSION_SECONDS
            with pytest.raises(MiniAppError):
                await store.profile(raw)
            for flag in ('archived', 'bot_blocked', 'moderation_revision'):
                profile, raw = await store.start()
                async with db.transaction() as session:
                    row = await session.get(GuestSession, credential_hash(raw))
                    account = await session.get(Account, row.account_id)
                    setattr(account, flag, 1 if flag == 'moderation_revision' else True)
                with pytest.raises(MiniAppError):
                    await store.resume(raw)
    asyncio.run(run())


def test_concurrent_renewal_and_lost_response_are_retryable(guest_pg_url):
    async def run():
        async with isolated_database(guest_pg_url) as (db, _):
            store = GuestAccounts(db)
            _, raw = await store.start()
            outcomes = await asyncio.gather(store.resume(raw), store.resume(raw), return_exceptions=True)
            assert all(isinstance(item, tuple) and item[1] == raw for item in outcomes)
            assert (await store.resume(raw))[1] == raw
    asyncio.run(run())


def test_guest_http_cookie_restart_and_telegram_separation(guest_pg_url):
    async def run():
        async with isolated_database(guest_pg_url) as (db, _):
            settings = MiniAppSettings('', ORIGIN, offline=True)
            app = create_app(database=db, settings=settings)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                response = await client.post('/api/guest/start', headers=HEADERS)
                assert response.status_code == 200
                cookie = response.headers['set-cookie']
                assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/' in cookie
                assert 'Secure' not in cookie
                aid = response.json()['account_id']
                assert (await client.post('/api/guest/start', headers=HEADERS)).json()['account_id'] == aid
                assert (await client.get('/api/mini/me')).status_code == 401
                assert (await client.post('/api/mini/session', json={})).status_code == 503
                app2 = create_app(database=db, settings=settings)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url=ORIGIN,
                                            cookies=client.cookies) as restarted:
                    assert (await restarted.get('/api/guest/me')).json()['account_id'] == aid
                    assert (await restarted.post('/api/guest/resume', headers=HEADERS)).status_code == 200
                    assert (await client.get('/api/guest/me')).status_code == 200
                    assert (await restarted.post('/api/guest/logout', headers=HEADERS)).status_code == 204
                    assert (await restarted.get('/api/guest/me')).status_code == 401
    asyncio.run(run())


def test_guest_boundaries_and_secure_cookie():
    async def run():
        for origin, offline in [(ORIGIN, True), ('https://quiz.example', False)]:
            app = create_app(database=SimpleNamespace(), settings=MiniAppSettings('', origin, offline=offline))
            app.state.guest_store.start = AsyncMock(return_value=({'account_id': 'test'}, 'a' * 43))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
                for headers in ({}, {'Origin': origin}, {'Origin': 'https://evil.example', 'X-Guest-CSRF': '1'},
                                {'Origin': origin, 'X-Guest-CSRF': '1', 'Sec-Fetch-Site': 'cross-site'}):
                    assert (await client.post('/api/guest/start', headers=headers)).status_code == 403
                headers = {'Origin': origin, 'X-Guest-CSRF': '1'}
                response = await client.post('/api/guest/start', headers=headers)
                assert response.status_code == 200
                assert ('Secure' in response.headers['set-cookie']) is (not offline)
                for _ in range(9):
                    assert (await client.post('/api/guest/start', headers=headers)).status_code == 200
                assert (await client.post('/api/guest/start', headers=headers)).status_code == 429
        restricted = create_app(database=SimpleNamespace(), settings=MiniAppSettings('', ORIGIN, offline=True), allowed_user_ids={1})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restricted), base_url=ORIGIN) as client:
            assert (await client.post('/api/guest/start', headers=HEADERS)).status_code == 403
    asyncio.run(run())


def test_alchemy_html_scopes_guest_before_game_boot_and_telegram_mode_is_explicit():
    async def run():
        app = create_app(database=SimpleNamespace(), settings=MiniAppSettings('', ORIGIN, offline=True))
        guest_id = '11111111-1111-4111-8111-111111111111'
        async def scoped_profile(credential):
            if not credential:
                raise MiniAppError(401, 'Гостевая сессия завершена')
            return {'account_id': guest_id}
        app.state.guest_store.profile = AsyncMock(side_effect=scoped_profile)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            client.cookies.set('mqb_guest', 'a' * 43)
            page = await client.get('/app/alchemy?mode=guest')
            assert page.status_code == 200
            assert page.headers['cache-control'] == 'no-store'
            source = page.text
            scope_at = source.index('window.MQB_ALCHEMY_GUEST_ID=')
            game_at = source.index('const GUEST_ID=')
            assert scope_at < game_at
            assert guest_id in source
            assert 'alchemia.atlas.guest.' in source
            telegram = await client.get('/app/alchemy?mode=telegram')
            assert telegram.status_code == 200
            assert 'window.MQB_ALCHEMY_GUEST_ID=null;' in telegram.text
            client.cookies.clear()
            assert (await client.get('/app/alchemy?mode=guest')).status_code == 401
    asyncio.run(run())


def test_migration_backfills_unique_accounts_and_preserves_users(guest_pg_url, monkeypatch):
    async def run():
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from alembic.script import ScriptDirectory
        migration = ScriptDirectory.from_config(Config('alembic.ini')).get_revision('20261007_0014').module
        async with isolated_database(guest_pg_url) as (db, _):
            async with db.transaction() as session:
                session.add_all([User(id=901, display_name='Alice', bot_blocked=True,
                                      moderation_revision=3, moderation_reason='blocked'),
                                 User(id=902, display_name='Bob')])
            async with db.engine.begin() as connection:
                def roundtrip(sync):
                    operations = Operations(MigrationContext.configure(sync))
                    # Base-created constraints use generated PG names; recreate
                    # the pre-0014 schema without relying on those names.
                    operations.drop_table('alchemy_progress')
                    operations.drop_table('guest_sessions')
                    operations.drop_column('users', 'account_id')
                    operations.drop_table('accounts')
                    before = list(sync.execute(text('SELECT * FROM users ORDER BY id')).mappings())
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', operations)
                        migration.upgrade()
                        after = list(sync.execute(text('SELECT * FROM users ORDER BY id')).mappings())
                        assert [{k: v for k, v in row.items() if k != 'account_id'} for row in after] == [dict(row) for row in before]
                        assert len({row['account_id'] for row in after}) == 2
                        assert all(row['account_id'] is not None for row in after)
                        accounts = list(sync.execute(text('SELECT * FROM accounts')).mappings())
                        alice = next(row for row in accounts if row['display_name'] == 'Alice')
                        assert alice['bot_blocked'] and alice['moderation_revision'] == 3
                        migration.downgrade()
                        assert list(sync.execute(text('SELECT * FROM users ORDER BY id')).mappings()) == before
                        migration.upgrade()
                await connection.run_sync(roundtrip)
    asyncio.run(run())
