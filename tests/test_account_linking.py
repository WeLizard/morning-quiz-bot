"""Stage 2 Telegram linking: isolated PostgreSQL and signed HTTP boundaries.

PG cases accept only tests.local_database's disposable morning_quiz_test URL.
No DATABASE_URL fallback and no bot/network calls are permitted here.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4
import time

import httpx
import pytest
from sqlalchemy import func, select

from application.account_linking import AccountLinkingService
from qw_farm.integration import register_models
from qw_farm.persistence import Unit
from storage.alchemy import AlchemyService, BASE_ELEMENTS, load_catalog
from storage.guest_accounts import GuestAccounts
from storage.mini_app import MiniAppError, MiniAppStore
from storage.models import (Account, AccountIdentity, AchievementGrant,
                            AlchemyCraftCommand, AlchemyProgress, User)
from tests.local_database import isolated_database
from tests.test_mini_app import ORIGIN, TOKEN, signed
from tests.test_postgres_members import pg_env
from web.mini_app import MiniAppSettings, create_app
from web.mini_auth import validate_init_data

HEADERS = {'Origin': ORIGIN, 'X-Guest-CSRF': '1'}
LINK = '/api/account/telegram-link'
UID = 981031000001


def identity(now, uid=UID):
    return validate_init_data(signed(uid, date=now, query_id=uuid4().hex), TOKEN, now=now)


def confirmation(account_id, now, uid=UID):
    return {'init_data': signed(uid, date=now, query_id=uuid4().hex), 'confirm': True,
            'account_id': str(account_id), 'telegram_user_id': str(uid)}


@asynccontextmanager
async def environment(url, monkeypatch):
    monkeypatch.setenv('QW_FARM_ENABLED', '1')
    schema = register_models()
    async with isolated_database(url) as (db, schema_name):
        async with db.transaction() as session:
            assert await session.scalar(select(func.current_database())) == 'morning_quiz_test'
            assert await session.scalar(select(func.current_user())) == 'mqb_dev'
            assert await session.scalar(select(func.current_schema())) == schema_name
        # Alchemy uses a real UTC clock too; credentials remain fresh in both adapters.
        now = int(time.time())
        app = create_app(database=db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True),
                         clock=lambda: now)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            response = await client.post('/api/guest/start', headers=HEADERS)
            assert response.status_code == 200, response.text
            yield SimpleNamespace(db=db, schema=schema, client=client, app=app, now=now,
                                  account_id=UUID(response.json()['account_id']),
                                  raw=client.cookies.get('mqb_guest'))


async def snapshot(db):
    """Capture persistent ownership/progress, including receipts and reward grants."""
    async with db.transaction() as session:
        return {model.__tablename__: [dict(row) for row in
                (await session.execute(select(model.__table__))).mappings()]
                for model in (Account, User, AccountIdentity, AlchemyProgress,
                              AlchemyCraftCommand, AchievementGrant)}


@pytest.mark.parametrize('endpoint', ['preview', 'confirm'])
def test_link_http_rejects_origin_csrf_and_invalid_signed_data(endpoint, monkeypatch):
    async def run():
        now = int(time.time())
        service = AsyncMock()
        monkeypatch.setattr(AccountLinkingService, 'telegram', service)
        app = create_app(database=SimpleNamespace(),
                         settings=MiniAppSettings(TOKEN, ORIGIN, offline=True), clock=lambda: now)
        body = confirmation(uuid4(), now) if endpoint == 'confirm' else {'init_data': signed(date=now)}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            for headers in ({}, {'Origin': ORIGIN}, {'X-Guest-CSRF': '1'},
                            {**HEADERS, 'Origin': 'https://evil.example'},
                            {**HEADERS, 'Sec-Fetch-Site': 'cross-site'}):
                response = await client.post(LINK + '/' + endpoint, headers=headers, json=body)
                assert response.status_code == 403
            for raw in (signed(date=now) + '0', signed(date=now - 301), signed(date=now + 31),
                        signed(date=now).replace('auth_date=', 'auth_date=1')):
                response = await client.post(LINK + '/' + endpoint, headers=HEADERS,
                                             json={**body, 'init_data': raw})
                assert response.status_code == 401, response.text
            service.assert_not_awaited()
    asyncio.run(run())


def test_link_http_confirmation_contract(monkeypatch):
    async def run():
        now = int(time.time())
        service = AsyncMock()
        monkeypatch.setattr(AccountLinkingService, 'telegram', service)
        app = create_app(database=SimpleNamespace(),
                         settings=MiniAppSettings(TOKEN, ORIGIN, offline=True), clock=lambda: now)
        valid = confirmation(uuid4(), now)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            for body in ({'init_data': valid['init_data']}, {**valid, 'confirm': False},
                         {**valid, 'confirm': 1}, {**valid, 'telegram_user_id': UID},
                         {**valid, 'extra': True}):
                response = await client.post(LINK + '/confirm', headers=HEADERS, json=body)
                assert response.status_code == 400, response.text
            response = await client.post(LINK + '/confirm', headers=HEADERS, content='{}')
            assert response.status_code == 415
            service.assert_not_awaited()
    asyncio.run(run())


def test_link_preserves_guest_farm_progress_and_repeated_confirmation(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            client = env.client
            farm = await client.post('/api/farm/v1/start?identity=guest',
                                     headers={'Origin': ORIGIN, 'X-QW-Farm': '1'})
            assert farm.status_code == 200, farm.text
            farm_id = farm.json()['farm']['id']
            async with env.db.transaction() as session:
                original_farm = await Unit(session, env.schema).by_account(str(env.account_id))
            alchemy = AlchemyService(env.db)
            await alchemy.guest_sync(env.raw, expected_account_id=str(env.account_id),
                                     discovered=['fire', 'water', 'steam'], attempts=12)
            before = await snapshot(env.db)
            preview = await client.post(LINK + '/preview', headers=HEADERS,
                                        json={'init_data': signed(UID, date=env.now)})
            assert preview.status_code == 200, preview.text
            assert preview.json()['account_id'] == str(env.account_id)
            assert preview.json()['already_linked'] is False
            assert await snapshot(env.db) == before  # Preview must not provision User/Account.
            body = confirmation(env.account_id, env.now)
            confirmed = await client.post(LINK + '/confirm', headers=HEADERS, json=body)
            assert confirmed.status_code == 200, confirmed.text
            assert confirmed.json()['profile']['account_id'] == str(env.account_id)
            assert confirmed.json()['profile']['telegram_user_id'] == str(UID)
            linked = await snapshot(env.db)
            repeated = await client.post(LINK + '/confirm', headers=HEADERS, json=body)
            assert repeated.status_code == 200 and repeated.json()['already_linked']
            assert await snapshot(env.db) == linked
            login = await client.post('/api/mini/session', json={
                'init_data': signed(UID, date=env.now, query_id=uuid4().hex)})
            assert login.status_code == 200, login.text
            assert (await client.get('/api/guest/me')).json()['account_id'] == str(env.account_id)
            for channel in ('guest', 'telegram'):
                view = await client.get('/api/farm/v1/me', params={'identity': channel})
                assert view.status_code == 200 and view.json()['farm']['id'] == farm_id
            async with env.db.transaction() as session:
                assert await Unit(session, env.schema).by_account(str(env.account_id)) == original_farm
                assert await session.scalar(select(func.count()).select_from(Account)) == 1
                row = await session.get(AlchemyProgress, env.account_id)
                assert row.user_id == UID and row.attempts == 12 and 'steam' in row.discovered
                assert set(row.verified_discovered) == BASE_ELEMENTS
                assert row.points_total == 0
    asyncio.run(run())


def test_existing_telegram_account_conflicts_without_changes(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            mini = MiniAppStore(env.db, TOKEN, clock=lambda: env.now)
            await mini.create_session(identity(env.now))
            await AlchemyService(env.db).guest_sync(env.raw,
                expected_account_id=str(env.account_id), discovered=['steam'], attempts=9)
            before = await snapshot(env.db)
            for endpoint, body in (
                ('preview', {'init_data': signed(UID, date=env.now)}),
                ('confirm', confirmation(env.account_id, env.now)),
            ):
                response = await env.client.post(LINK + '/' + endpoint, headers=HEADERS, json=body)
                assert response.status_code == 409, response.text
                assert response.json()['code'] == 'telegram_link_conflict'
                assert await snapshot(env.db) == before
    asyncio.run(run())


def test_changed_confirmation_and_post_flush_failure_roll_back(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            store = GuestAccounts(env.db, clock=lambda: env.now)
            service = AccountLinkingService(env.db, store)
            before = await snapshot(env.db)
            with pytest.raises(MiniAppError) as changed:
                await service.telegram(env.raw, identity(env.now), confirm=True,
                    expected_account_id=str(uuid4()), expected_telegram_user_id=str(UID))
            assert changed.value.status == 409 and changed.value.code == 'profile_changed'
            assert await snapshot(env.db) == before
            with monkeypatch.context() as patch:
                patch.setattr(store, 'projection_in', AsyncMock(side_effect=RuntimeError('injected after flush')))
                with pytest.raises(RuntimeError, match='injected after flush'):
                    await service.telegram(env.raw, identity(env.now), confirm=True,
                        expected_account_id=str(env.account_id), expected_telegram_user_id=str(UID))
            assert await snapshot(env.db) == before
    asyncio.run(run())


@pytest.mark.parametrize('login_first', [False, True])
def test_concurrent_link_and_normal_login_have_one_owner(pg_env, monkeypatch, login_first):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            service = AccountLinkingService(env.db, GuestAccounts(env.db, clock=lambda: env.now))
            mini = MiniAppStore(env.db, TOKEN, clock=lambda: env.now)
            start = asyncio.Event()
            async def link():
                await start.wait()
                return await service.telegram(env.raw, identity(env.now), confirm=True,
                    expected_account_id=str(env.account_id), expected_telegram_user_id=str(UID))
            async def login():
                await start.wait()
                return await mini.create_session(identity(env.now))
            calls = [login(), link()] if login_first else [link(), login()]
            tasks = [asyncio.create_task(call) for call in calls]
            start.set()
            outcomes = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 15)
            linked = outcomes[1 if login_first else 0]
            logged = outcomes[0 if login_first else 1]
            assert isinstance(logged, dict), logged
            assert isinstance(linked, dict) or (isinstance(linked, MiniAppError) and linked.status == 409), linked
            async with env.db.transaction() as session:
                user = await session.get(User, UID)
                mappings = (await session.scalars(select(AccountIdentity).where(
                    AccountIdentity.provider == 'telegram', AccountIdentity.provider_subject == str(UID)))).all()
                assert len(mappings) == 1 and mappings[0].account_id == user.account_id
                assert mappings[0].verified_at is not None
                count = await session.scalar(select(func.count()).select_from(Account))
                if isinstance(linked, dict):
                    assert user.account_id == env.account_id and count == 1
                else:
                    assert user.account_id != env.account_id and count == 2
            assert (await env.client.get('/api/guest/me')).json()['account_id'] == str(env.account_id)
    asyncio.run(run())


def test_two_telegram_users_cannot_link_same_account_concurrently(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            service = AccountLinkingService(env.db, GuestAccounts(env.db, clock=lambda: env.now))
            outcomes = await asyncio.wait_for(asyncio.gather(*[
                service.telegram(env.raw, identity(env.now, uid), confirm=True,
                    expected_account_id=str(env.account_id), expected_telegram_user_id=str(uid))
                for uid in (UID, UID + 1)], return_exceptions=True), 15)
            assert sum(isinstance(item, dict) for item in outcomes) == 1
            failures = [item for item in outcomes if isinstance(item, Exception)]
            assert len(failures) == 1 and isinstance(failures[0], MiniAppError) and failures[0].status == 409
            async with env.db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(User)) == 1
                assert await session.scalar(select(func.count()).select_from(AccountIdentity)) == 1
                assert await session.scalar(select(func.count()).select_from(Account)) == 1
    asyncio.run(run())


def test_linked_alchemy_channels_keep_offline_claims_unverified_and_awards_once(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            service = AlchemyService(env.db)
            catalog = load_catalog()
            await service.guest_sync(env.raw, expected_account_id=str(env.account_id),
                discovered=sorted(catalog.element_ids), crafted=sorted(catalog.recipe_keys), attempts=100)
            moment = datetime.fromtimestamp(env.now, timezone.utc)
            guest_craft = await service.guest_craft(env.raw, expected_account_id=str(env.account_id),
                command_id='link-guest-before', ingredient_a='earth', ingredient_b='earth', now=moment)
            assert guest_craft['verified'] and guest_craft['awarded'] == 0
            await AccountLinkingService(env.db, GuestAccounts(env.db, clock=lambda: env.now)).telegram(
                env.raw, identity(env.now), confirm=True, expected_account_id=str(env.account_id),
                expected_telegram_user_id=str(UID))
            imported = await service.sync(UID, discovered=sorted(catalog.element_ids),
                crafted=sorted(catalog.recipe_keys), now=moment)
            assert imported['awarded'] == 0
            assert set(imported['verified_discovered']) == BASE_ELEMENTS | {'stone'}
            replay = await service.craft(UID, command_id='link-guest-before',
                ingredient_a='earth', ingredient_b='earth', now=moment)
            assert replay == guest_craft  # Account-scoped receipt crosses channels.
            after_link = await service.guest_craft(env.raw, expected_account_id=str(env.account_id),
                command_id='link-guest-after', ingredient_a='earth', ingredient_b='earth', now=moment)
            assert after_link['verified'] and after_link['awarded'] == 0
            craft = await service.craft(UID, command_id='link-rated-command',
                ingredient_a='fire', ingredient_b='water', now=moment)
            assert craft['verified'] and craft['awarded'] > 0
            repeated = await service.guest_craft(env.raw, expected_account_id=str(env.account_id),
                command_id='link-rated-command', ingredient_a='fire', ingredient_b='water', now=moment)
            assert repeated == craft
            await service.guest_sync(env.raw, expected_account_id=str(env.account_id),
                                     discovered=sorted(catalog.element_ids), now=moment)
            async with env.db.transaction() as session:
                row = await session.get(AlchemyProgress, env.account_id)
                user = await session.get(User, UID)
                assert row.user_id == UID
                assert set(row.verified_discovered) == BASE_ELEMENTS | {'stone', 'steam'}
                assert float(row.points_total) == craft['awarded'] == float(user.global_score)
                assert await session.scalar(select(func.count()).select_from(AlchemyProgress)) == 1
                assert await session.scalar(select(func.count()).select_from(AlchemyCraftCommand)) == 3
                codes = (await session.scalars(select(AchievementGrant.code))).all()
                assert len(codes) == len(set(codes))
            mini = MiniAppStore(env.db, TOKEN, clock=lambda: env.now)
            token = (await mini.create_session(identity(env.now)))['access_token']
            pg = await mini.alchemy_progress(token, expected_user_id=str(UID))
            guest = await service.guest_progress(env.raw, now=moment)
            assert pg['verified_discovered_ids'] == guest['verified_discovered']
    asyncio.run(run())
