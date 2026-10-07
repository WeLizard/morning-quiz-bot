"""Account-owned guest Alchemy acceptance, only disposable local PostgreSQL."""
import asyncio
import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
import httpx
from sqlalchemy import func, select, text, inspect

from storage.alchemy import AlchemyService, load_catalog
from storage.database import normalize_database_url
from storage.guest_accounts import GuestAccounts
from storage.mini_app import MiniAppError
from storage.models import Account, AchievementGrant, AlchemyProgress, User
from tests.local_database import isolated_database
from web.mini_app import MiniAppSettings, create_app


@pytest.fixture
def guest_alchemy_url():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL is required; no production fallback')
    return normalize_database_url(url)


def test_guest_merge_restart_isolation_and_no_rewards(guest_alchemy_url):
    async def run():
        async with isolated_database(guest_alchemy_url) as (db, _):
            auth = GuestAccounts(db)
            first, raw = await auth.start()
            second, other_raw = await auth.start()
            service = AlchemyService(db)
            catalog = load_catalog()
            elements = sorted(catalog.element_ids)[:7]
            recipe = sorted(catalog.recipe_keys)[0]
            await asyncio.gather(
                service.guest_sync(raw, expected_account_id=first['account_id'], discovered=elements[:4], attempts=20),
                service.guest_sync(raw, expected_account_id=first['account_id'], discovered=elements[4:] + ['INVALID'], crafted=[recipe], attempts=3))
            restored = await AlchemyService(db).guest_progress(raw)
            assert restored['discovered'] == elements and restored['crafted'] == [recipe]
            assert restored['attempts'] == 20 and restored['awarded'] == 0
            assert restored['reward_eligible'] is False and restored['points_total'] == 0
            assert (await service.guest_progress(other_raw))['discovered'] == []
            repeated = await service.guest_sync(raw, expected_account_id=first['account_id'], discovered=[], attempts=0)
            assert repeated == restored
            with pytest.raises(MiniAppError) as mismatch:
                await service.guest_sync(other_raw, expected_account_id=first['account_id'], discovered=elements)
            assert mismatch.value.status == 409
            assert (await service.guest_progress(other_raw))['discovered'] == []
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(User)) == 0
                assert await session.scalar(select(func.count()).select_from(AchievementGrant)) == 0
                row = await session.get(AlchemyProgress, UUID(first['account_id']))
                assert row.user_id is None and row.points_total == Decimal('0')
                account = await session.get(Account, UUID(first['account_id']))
                account.moderation_revision += 1
            with pytest.raises(MiniAppError):
                await service.guest_sync(raw, expected_account_id=first['account_id'], discovered=elements)
            await auth.logout(other_raw)
            with pytest.raises(MiniAppError):
                await service.guest_progress(other_raw)
    asyncio.run(run())


def test_telegram_and_guest_progress_have_independent_owners(guest_alchemy_url):
    async def run():
        async with isolated_database(guest_alchemy_url) as (db, _):
            guest, raw = await GuestAccounts(db).start()
            service = AlchemyService(db)
            elements = sorted(load_catalog().element_ids)[:3]
            await service.guest_sync(raw, expected_account_id=guest['account_id'], discovered=elements)
            await service.sync(901, discovered=elements[:1])
            guest = await service.guest_progress(raw)
            telegram = await service.progress(901)
            assert len(guest['discovered']) == 3 and telegram['discovered'] == 1
            assert telegram['total_players'] == 1
            board = await service.leaderboard(user_id=901)
            assert len(board['items']) == 1 and board['items'][0]['is_me']
            async with db.transaction() as session:
                user = await session.get(User, 901)
                rows = (await session.scalars(select(AlchemyProgress))).all()
                assert len(rows) == 2 and user.account_id is not None
                assert next(row for row in rows if row.user_id == 901).account_id == user.account_id
                assert user.global_score > 0
    asyncio.run(run())


def test_guest_alchemy_http_restart_and_stale_tab_rejected(guest_alchemy_url):
    async def run():
        origin = 'http://127.0.0.1:4185'
        headers = {'Origin': origin, 'X-Guest-CSRF': '1'}
        async with isolated_database(guest_alchemy_url) as (db, _):
            app = create_app(database=db, settings=MiniAppSettings('', origin, offline=True))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as first:
                profile = (await first.post('/api/guest/start', headers=headers)).json()
                account_id = profile['account_id']
                game = await first.get('/app/alchemy?mode=guest')
                assert game.status_code == 200 and account_id in game.text
                assert game.text.index('window.MQB_ALCHEMY_GUEST_ID=') < game.text.index('const GUEST_ID=')
                sync_headers = {**headers, 'X-Guest-Account': account_id}
                saved = await first.post('/api/guest/alchemy/sync', headers=sync_headers,
                    json={'discovered': ['water', 'earth', 'fire', 'air', 'steam'],
                          'crafted': ['air+water'], 'attempts': 6})
                assert saved.status_code == 200 and 'steam' in saved.json()['discovered']
                assert saved.json()['reward_eligible'] is False
                restarted = create_app(database=db, settings=MiniAppSettings('', origin, offline=True))
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted),
                                             base_url=origin, cookies=first.cookies) as resumed:
                    assert (await resumed.get('/api/guest/me')).json()['account_id'] == account_id
                    restored = (await resumed.get('/api/guest/alchemy')).json()
                    assert 'steam' in restored['discovered'] and restored['attempts'] == 6
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as second:
                    second_id = (await second.post('/api/guest/start', headers=headers)).json()['account_id']
                    assert second_id != account_id
                    stale = await second.post('/api/guest/alchemy/sync', headers=sync_headers,
                        json={'discovered': ['steam']})
                    assert stale.status_code == 409
                    assert (await second.get('/api/guest/alchemy')).json()['discovered'] == []
                    assert (await second.post('/api/guest/alchemy/sync', headers=headers,
                        json={'discovered': ['steam']})).status_code == 422
    asyncio.run(run())


def test_alchemy_migration_roundtrip_and_guest_downgrade_guard(guest_alchemy_url, monkeypatch):
    async def run():
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from alembic.script import ScriptDirectory
        scripts = ScriptDirectory.from_config(Config('alembic.ini'))
        migration = scripts.get_revision('20261007_0015').module
        auth_migration = scripts.get_revision('20261007_0014').module
        async with isolated_database(guest_alchemy_url) as (db, _):
            await AlchemyService(db).sync(901, discovered=sorted(load_catalog().element_ids)[:3])
            async with db.engine.begin() as connection:
                def roundtrip(sync):
                    operations = Operations(MigrationContext.configure(sync))
                    for constraint in inspect(sync).get_unique_constraints('alchemy_progress'):
                        operations.drop_constraint(constraint['name'], 'alchemy_progress', type_='unique')
                    operations.drop_column('alchemy_progress', 'account_id')
                    operations.drop_column('alchemy_progress', 'attempts')
                    operations.alter_column('alchemy_progress', 'user_id', nullable=False)
                    operations.create_primary_key('alchemy_progress_pkey', 'alchemy_progress', ['user_id'])
                    before = list(sync.execute(text('SELECT * FROM alchemy_progress')).mappings())
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', operations)
                        migration.upgrade()
                        after = list(sync.execute(text('SELECT * FROM alchemy_progress')).mappings())
                        assert [{k: v for k, v in row.items() if k not in ('account_id', 'attempts')} for row in after] == [dict(row) for row in before]
                        migration.downgrade()
                        assert list(sync.execute(text('SELECT * FROM alchemy_progress')).mappings()) == before
                        migration.upgrade()
                await connection.run_sync(roundtrip)
            guest, raw = await GuestAccounts(db).start()
            await AlchemyService(db).guest_sync(raw, expected_account_id=guest['account_id'], discovered=['fire'])
            async with db.engine.begin() as connection:
                def blocked(sync):
                    operations = Operations(MigrationContext.configure(sync))
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', operations)
                        patch.setattr(auth_migration, 'op', operations)
                        with pytest.raises(RuntimeError, match='guest Alchemy'):
                            migration.downgrade()
                        with pytest.raises(RuntimeError, match='independent accounts'):
                            auth_migration.downgrade()
                    assert sync.scalar(text('SELECT COUNT(*) FROM alchemy_progress')) == 2
                await connection.run_sync(blocked)
    asyncio.run(run())
