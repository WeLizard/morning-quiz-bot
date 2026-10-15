"""Login + password accounts: register, upgrade of a guest, login, limits, logout."""
import asyncio
import os

import httpx
import pytest
from sqlalchemy import func, select

from storage.account_passwords import (AttemptLimiter, PasswordAccounts, hash_password,
                                       normalize_login, verify_password)
from storage.database import normalize_database_url
from storage.guest_accounts import GuestAccounts
from storage.mini_app import MiniAppError
from storage.models import Account, AccountCredential, AccountIdentity, GuestSession
from tests.local_database import isolated_database
from web.mini_app import MiniAppSettings, create_app

ORIGIN = 'http://127.0.0.1:4185'
HEADERS = {'Origin': ORIGIN, 'X-Guest-CSRF': '1'}
PASSWORD = 'correct horse battery'


@pytest.fixture
def pg_url():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL is not configured; no production fallback')
    return normalize_database_url(url)


def client_for(db):
    app = create_app(database=db, settings=MiniAppSettings('', ORIGIN, offline=True))
    return app, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)


def test_password_hash_and_login_rules():
    stored = hash_password(PASSWORD)
    assert stored.startswith('scrypt$') and PASSWORD not in stored
    assert stored != hash_password(PASSWORD)          # random salt
    assert verify_password(PASSWORD, stored)
    assert not verify_password(PASSWORD + 'x', stored)
    assert not verify_password(PASSWORD, 'garbage') and not verify_password(PASSWORD, 'scrypt$1$2')
    assert normalize_login('  Ilya.Test-1_ ') == 'ilya.test-1_'
    for bad in ('ab', 'a' * 33, 'bad login', 'ёжик', '', None, 5):
        with pytest.raises(MiniAppError) as error:
            normalize_login(bad)
        assert error.value.status == 400


def test_attempt_limiter_window():
    now = [0.0]
    limiter = AttemptLimiter(limit=3, window=100, clock=lambda: now[0])
    limiter.fail('a'); limiter.fail('a')
    assert not limiter.blocked('a', 'b')
    limiter.fail('a')
    assert limiter.blocked('a') and not limiter.blocked('b')
    now[0] = 101
    assert not limiter.blocked('a')


def test_register_login_duplicate_and_generic_failure(pg_url):
    async def run():
        async with isolated_database(pg_url) as (db, _):
            app, client = client_for(db)
            async with client:
                body = {'login': 'Ilya_One', 'password': PASSWORD, 'display_name': 'Илья'}
                response = await client.post('/api/account/register', headers=HEADERS, json=body)
                assert response.status_code == 200, response.text
                profile = response.json()
                assert profile['login'] == 'ilya_one' and profile['display_name'] == 'Илья'
                assert 'HttpOnly' in response.headers['set-cookie']
                # The cookie is a normal guest-session cookie: /api/guest/* works.
                me = await client.get('/api/guest/me')
                assert me.json()['account_id'] == profile['account_id'] and me.json()['login'] == 'ilya_one'
                async with db.transaction() as session:
                    cred = await session.get(AccountCredential, __import__('uuid').UUID(profile['account_id']))
                    assert cred.password_hash.startswith('scrypt$') and PASSWORD not in cred.password_hash
                    identity = await session.scalar(select(AccountIdentity).where(
                        AccountIdentity.provider == 'password'))
                    assert identity.provider_subject == 'ilya_one' and identity.verified_at is not None

                # Another browser: duplicate login (case-insensitive) conflicts.
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as other:
                    duplicate = await other.post('/api/account/register', headers=HEADERS,
                                                 json={'login': 'ILYA_ONE', 'password': PASSWORD})
                    assert duplicate.status_code == 409
                    short = await other.post('/api/account/register', headers=HEADERS,
                                             json={'login': 'ilya_two', 'password': 'short'})
                    assert short.status_code == 400
                    assert (await other.post('/api/account/register', headers=HEADERS,
                                             json={'login': 'ilya_two', 'password': PASSWORD, 'extra': 1})).status_code == 400
                    # Login: success creates a session for the same account.
                    ok = await other.post('/api/account/login', headers=HEADERS,
                                          json={'login': 'Ilya_One', 'password': PASSWORD})
                    assert ok.status_code == 200 and ok.json()['account_id'] == profile['account_id']
                    assert (await other.get('/api/guest/me')).json()['login'] == 'ilya_one'
                    # Unknown login and wrong password are indistinguishable.
                    wrong = await other.post('/api/account/login', headers=HEADERS,
                                             json={'login': 'ilya_one', 'password': 'wrong password'})
                    unknown = await other.post('/api/account/login', headers=HEADERS,
                                               json={'login': 'nobody_here', 'password': 'wrong password'})
                    assert wrong.status_code == unknown.status_code == 401
                    assert wrong.json() == unknown.json()
                    # CSRF boundary applies to /api/account/*.
                    assert (await other.post('/api/account/login', json={'login': 'a', 'password': 'b'})).status_code == 403
    asyncio.run(run())


def test_guest_upgrade_keeps_account_and_logout(pg_url):
    async def run():
        async with isolated_database(pg_url) as (db, _):
            app, client = client_for(db)
            async with client:
                guest = (await client.post('/api/guest/start', headers=HEADERS)).json()
                assert guest['login'] is None
                cookie = client.cookies.get('mqb_guest')
                response = await client.post('/api/account/register', headers=HEADERS,
                                             json={'login': 'saved_guest', 'password': PASSWORD})
                assert response.status_code == 200
                assert response.json()['account_id'] == guest['account_id']
                assert 'set-cookie' not in response.headers          # same session, same cookie
                assert client.cookies.get('mqb_guest') == cookie
                async with db.transaction() as session:
                    assert await session.scalar(select(func.count()).select_from(Account)) == 1
                    assert (await session.get(Account, __import__('uuid').UUID(guest['account_id']))).display_name == 'saved_guest'
                # A second registration on an already protected profile is refused.
                again = await client.post('/api/account/register', headers=HEADERS,
                                          json={'login': 'another_one', 'password': PASSWORD})
                assert again.status_code == 409
                # Logout revokes the session and clears the cookie.
                assert (await client.post('/api/account/logout', headers=HEADERS)).status_code == 204
                assert (await client.get('/api/guest/me')).status_code == 401
                async with db.transaction() as session:
                    assert all(row.revoked for row in (await session.scalars(select(GuestSession))).all())
                # Progress survives: logging in returns the very same account.
                relogin = await client.post('/api/account/login', headers=HEADERS,
                                            json={'login': 'saved_guest', 'password': PASSWORD})
                assert relogin.json()['account_id'] == guest['account_id']
    asyncio.run(run())


def test_login_rate_limit_per_login_and_ip(pg_url):
    async def run():
        async with isolated_database(pg_url) as (db, _):
            now = [0.0]
            guests = GuestAccounts(db)
            store = PasswordAccounts(guests, AttemptLimiter(limit=10, window=900, clock=lambda: now[0]))
            await store.register('victim_user', PASSWORD)
            for _ in range(10):
                with pytest.raises(MiniAppError) as error:
                    await store.login('victim_user', 'wrong password', '10.0.0.1')
                assert error.value.status == 401
            # The login is now locked, even for the right password and another IP.
            for ip in ('10.0.0.1', '10.0.0.2'):
                with pytest.raises(MiniAppError) as error:
                    await store.login('victim_user', PASSWORD, ip)
                assert error.value.status == 429
            # One IP guessing many logins is limited too.
            for index in range(10):
                with pytest.raises(MiniAppError):
                    await store.login(f'ghost_{index}', 'wrong password', '10.0.0.9')
            with pytest.raises(MiniAppError) as error:
                await store.login('victim_user2', PASSWORD, '10.0.0.9')
            assert error.value.status == 429
            # The window expires.
            now[0] += 901
            profile, raw = await store.login('victim_user', PASSWORD, '10.0.0.1')
            assert profile['login'] == 'victim_user' and raw
    asyncio.run(run())
