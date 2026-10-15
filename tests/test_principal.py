"""Shared account principal: Telegram Mini App session and guest/password session."""
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.engine import make_url

from storage.database import normalize_database_url
from storage.mini_app import MiniAppError
from storage.models import Account, User
from tests.local_database import isolated_database
from tests.test_mini_app import NOW, ORIGIN, TOKEN, signed
from web.mini_app import MiniAppSettings, create_app
from web.principal import MINI_COOKIE, GUEST_COOKIE, PrincipalError, resolve_principal

GUEST_HEADERS = {'Origin': ORIGIN, 'X-Guest-CSRF': '1'}
TG_USER = 981030000001


@pytest.fixture
def pg_url():
    raw = os.getenv('TEST_DATABASE_URL')
    if not raw:
        pytest.skip('TEST_DATABASE_URL is not configured')
    url = normalize_database_url(raw)
    if make_url(url).database != 'morning_quiz_test':
        pytest.fail('Principal tests require PostgreSQL morning_quiz_test')
    return url


@asynccontextmanager
async def environment(url):
    async with isolated_database(url) as (db, _):
        app = create_app(database=db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True), clock=lambda: NOW)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            guest = (await client.post('/api/guest/start', headers=GUEST_HEADERS)).json()
            guest_cookie = client.cookies.get(GUEST_COOKIE)
            account_id = uuid4()
            async with db.transaction() as session:
                session.add(Account(id=account_id, display_name='Telegram'))
                await session.flush()
                session.add(User(id=TG_USER, account_id=account_id, display_name='Telegram'))
            response = await client.post('/api/mini/session', json={
                'init_data': signed(TG_USER, date=NOW, query_id=uuid4().hex)})
            assert response.status_code == 200, response.text
            yield SimpleNamespace(db=db, app=app, guest=guest, guest_cookie=guest_cookie,
                                  mini_cookie=client.cookies.get(MINI_COOKIE), telegram_account=str(account_id))


def request(cookies=None, **query):
    return SimpleNamespace(cookies=cookies or {}, query_params=query)


async def resolve(env, req, **kwargs):
    async with resolve_principal(req, database=env.db, guest_store=env.app.state.guest_store,
                                 mini_store=env.app.state.mini_store, **kwargs) as (session, principal):
        assert session is not None
        return principal


@pytest.mark.parametrize('lock', [False, True])
def test_only_mini_cookie_resolves_telegram_principal(pg_url, lock):
    import asyncio

    async def run():
        async with environment(pg_url) as env:
            principal = await resolve(env, request({MINI_COOKIE: env.mini_cookie}), lock=lock)
            assert (principal.channel, principal.account_id, principal.telegram_user_id) == (
                'telegram', env.telegram_account, TG_USER)
    asyncio.run(run())


@pytest.mark.parametrize('lock', [False, True])
def test_only_guest_cookie_resolves_guest_principal(pg_url, lock):
    import asyncio

    async def run():
        async with environment(pg_url) as env:
            principal = await resolve(env, request({GUEST_COOKIE: env.guest_cookie}), lock=lock)
            assert (principal.channel, principal.account_id, principal.telegram_user_id) == (
                'guest', env.guest['account_id'], None)
    asyncio.run(run())


def test_both_cookies_require_explicit_identity(pg_url):
    import asyncio

    async def run():
        async with environment(pg_url) as env:
            cookies = {GUEST_COOKIE: env.guest_cookie, MINI_COOKIE: env.mini_cookie}
            with pytest.raises(PrincipalError) as error:
                await resolve(env, request(cookies))
            assert error.value.code == 'identity_required' and error.value.status == 401
            guest = await resolve(env, request(cookies), identity='guest')
            telegram = await resolve(env, request(cookies), identity='telegram')
            assert guest.channel == 'guest' and guest.account_id == env.guest['account_id']
            assert telegram.channel == 'telegram' and telegram.account_id == env.telegram_account
            with pytest.raises(PrincipalError) as error:
                await resolve(env, request(cookies), identity='other')
            assert error.value.status == 422
    asyncio.run(run())


def test_banned_user_and_account_are_rejected(pg_url):
    import asyncio

    async def run():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                await session.execute(update(User).where(User.id == TG_USER).values(bot_blocked=True))
                await session.execute(update(Account).where(Account.id == UUID(env.guest['account_id']))
                                      .values(bot_blocked=True))
            for cookies in ({MINI_COOKIE: env.mini_cookie}, {GUEST_COOKIE: env.guest_cookie}):
                with pytest.raises(MiniAppError) as error:
                    await resolve(env, request(cookies), lock=True)
                assert error.value.status == 401
    asyncio.run(run())


def test_missing_or_garbage_credentials_are_rejected(pg_url):
    import asyncio

    async def run():
        async with environment(pg_url) as env:
            with pytest.raises(MiniAppError) as error:
                await resolve(env, request())
            assert error.value.status == 401
            with pytest.raises(MiniAppError):
                await resolve(env, request({GUEST_COOKIE: 'x'}))
            with pytest.raises(MiniAppError):
                await resolve(env, request({MINI_COOKIE: 'x' * 43}))
            with pytest.raises(PrincipalError) as error:
                await resolve(env, request(), identity='telegram')
            assert error.value.code == 'authentication'
    asyncio.run(run())
