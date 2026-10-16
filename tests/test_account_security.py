"""Credentials for any account, password change/recovery and the device list (PG + HTTP)."""
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4
import time

import httpx
from sqlalchemy import select

from storage.guest_accounts import GuestAccounts
from storage.models import Account, GuestSession, MiniAppSession
from tests.local_database import isolated_database
from tests.test_mini_app import ORIGIN, TOKEN, signed
from tests.test_postgres_members import pg_env  # noqa: F401  (fixture)
from web.client_hint import client_hint
from web.mini_app import MiniAppSettings, create_app

HEADERS = {'Origin': ORIGIN, 'X-Guest-CSRF': '1'}
PASSWORD = 'correct horse battery'
NEW_PASSWORD = 'another long passphrase'
UID = 981032000001
CHROME = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
          'Chrome/126.0.0.0 Safari/537.36')


def test_client_hint_labels():
    assert client_hint(CHROME) == 'Chrome · Windows'
    assert client_hint('Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 '
                       '(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1') == 'Safari · iPhone'
    assert client_hint(CHROME + ' Edg/126.0') == 'Edge · Windows'
    assert client_hint(None) == client_hint('') == 'Неизвестное устройство'
    assert len(client_hint('Chrome/1 ' * 500)) <= 60


@asynccontextmanager
async def environment(url):
    async with isolated_database(url) as (db, _):
        now = int(time.time())
        app = create_app(database=db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True),
                         clock=lambda: now)

        def browser(agent=None):
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                                     headers={'User-Agent': agent} if agent else None)

        env = SimpleNamespace(db=db, now=now, browser=browser, opened=[], app=app)
        try:
            yield env
        finally:
            for client in env.opened:
                await client.aclose()


async def telegram_browser(env, uid=UID):
    client = await env.browser().__aenter__()
    env.opened.append(client)
    response = await client.post('/api/mini/session', json={
        'init_data': signed(uid, date=env.now, query_id=uuid4().hex)})
    assert response.status_code == 200, response.text
    return client


async def account_of(client):
    return (await client.get('/api/account/sessions')).status_code


def test_telegram_account_sets_login_and_signs_in_elsewhere(pg_env):
    async def run():
        async with environment(pg_env) as env:
            tg = await telegram_browser(env)
            if True:
                bad = await tg.post('/api/account/credentials', headers=HEADERS,
                                    json={'login': 'x', 'password': PASSWORD})
                assert bad.status_code == 400
                ok = await tg.post('/api/account/credentials', headers=HEADERS,
                                   json={'login': 'Tg_Player', 'password': PASSWORD})
                assert ok.status_code == 200, ok.text
                account_id = ok.json()['account_id']
                assert ok.json()['login'] == 'tg_player'
                # Repeating on an account that already has a login is a conflict.
                again = await tg.post('/api/account/credentials', headers=HEADERS,
                                      json={'login': 'other_login', 'password': PASSWORD})
                assert again.status_code == 409
                async with env.browser(CHROME) as other:
                    login = await other.post('/api/account/login', headers=HEADERS,
                                             json={'login': 'TG_PLAYER', 'password': PASSWORD})
                    assert login.status_code == 200 and login.json()['account_id'] == account_id
                    listing = (await other.get('/api/account/sessions')).json()
                    assert listing['has_password'] and listing['login'] == 'tg_player'
                    assert listing['telegram_linked'] and listing['can_reset_password']
                    assert listing['telegram_sessions'] == 1
                    [row] = listing['sessions']
                    assert row['current'] and row['created_via'] == 'password'
                    assert row['user_agent'] == 'Chrome · Windows' and len(row['id']) == 16
                # The Telegram browser sees the same account and list.
                seen = (await tg.get('/api/account/sessions')).json()
                assert seen['login'] == 'tg_player' and not any(s['current'] for s in seen['sessions'])
                # A login taken by another account is a conflict.
                tg2 = await telegram_browser(env, UID + 1)
                if True:
                    taken = await tg2.post('/api/account/credentials', headers=HEADERS,
                                           json={'login': 'tg_player', 'password': PASSWORD})
                    assert taken.status_code == 409
                    assert (await tg2.post('/api/account/credentials', json={
                        'login': 'free_one', 'password': PASSWORD})).status_code == 403   # CSRF
    asyncio.run(run())


def test_change_password_with_current_revokes_other_sessions(pg_env):
    async def run():
        async with environment(pg_env) as env:
            async with env.browser(CHROME) as first, env.browser() as second:
                reg = await first.post('/api/account/register', headers=HEADERS,
                                       json={'login': 'changer', 'password': PASSWORD})
                assert reg.status_code == 200
                assert (await second.post('/api/account/login', headers=HEADERS, json={
                    'login': 'changer', 'password': PASSWORD})).status_code == 200
                missing = await first.post('/api/account/password', headers=HEADERS,
                                           json={'new_password': NEW_PASSWORD})
                assert missing.status_code == 401
                wrong = await first.post('/api/account/password', headers=HEADERS, json={
                    'new_password': NEW_PASSWORD, 'current_password': 'not the password'})
                assert wrong.status_code == 401
                assert (await first.post('/api/account/password', headers=HEADERS, json={
                    'new_password': 'short', 'current_password': PASSWORD})).status_code == 400
                done = await first.post('/api/account/password', headers=HEADERS, json={
                    'new_password': NEW_PASSWORD, 'current_password': PASSWORD})
                assert done.status_code == 200 and done.json()['revoked_sessions'] == 1
                assert (await first.get('/api/guest/me')).status_code == 200      # current kept
                assert (await second.get('/api/guest/me')).status_code == 401     # others revoked
                async with env.browser() as fresh:
                    old = await fresh.post('/api/account/login', headers=HEADERS,
                                           json={'login': 'changer', 'password': PASSWORD})
                    new = await fresh.post('/api/account/login', headers=HEADERS,
                                           json={'login': 'changer', 'password': NEW_PASSWORD})
                    assert old.status_code == 401 and new.status_code == 200
            # An account without a password cannot "change" one.
            async with env.browser() as guest:
                await guest.post('/api/guest/start', headers=HEADERS)
                none = await guest.post('/api/account/password', headers=HEADERS, json={
                    'new_password': NEW_PASSWORD, 'current_password': PASSWORD})
                assert none.status_code == 409
    asyncio.run(run())


def test_recovery_by_fresh_telegram_session_and_stale_session(pg_env):
    async def run():
        async with environment(pg_env) as env:
            tg = await telegram_browser(env)
            async with env.browser() as old_browser, env.browser() as recovered:
                ok = await tg.post('/api/account/credentials', headers=HEADERS,
                                   json={'login': 'recover_me', 'password': PASSWORD})
                account_id = UUID(ok.json()['account_id'])
                assert (await old_browser.post('/api/account/login', headers=HEADERS, json={
                    'login': 'recover_me', 'password': PASSWORD})).status_code == 200
                # Browser Telegram login (part A) gives a session with created_via='telegram'.
                guests = GuestAccounts(env.db)
                async with env.db.transaction() as session:
                    raw, row = guests._session(await session.get(Account, account_id),
                                               created_via='telegram', user_agent='Chrome · Windows')
                    session.add(row)
                recovered.cookies.set('mqb_guest', raw)
                done = await recovered.post('/api/account/password', headers=HEADERS,
                                            json={'new_password': NEW_PASSWORD})
                assert done.status_code == 200, done.text
                assert (await old_browser.get('/api/guest/me')).status_code == 401
                assert (await recovered.get('/api/guest/me')).status_code == 200
                assert (await tg.get('/api/account/sessions')).status_code == 401   # mini session revoked
                async with env.db.transaction() as session:
                    assert all(r.revoked for r in (await session.scalars(select(MiniAppSession))).all())
                async with env.browser() as fresh:
                    assert (await fresh.post('/api/account/login', headers=HEADERS, json={
                        'login': 'recover_me', 'password': PASSWORD})).status_code == 401
                    assert (await fresh.post('/api/account/login', headers=HEADERS, json={
                        'login': 'recover_me', 'password': NEW_PASSWORD})).status_code == 200
                # The same session older than 15 minutes needs the current password.
                async with env.db.transaction() as session:
                    stale = await session.get(GuestSession, next(
                        r.token_hash for r in (await session.scalars(select(GuestSession))).all()
                        if r.created_via == 'telegram'))
                    stale.created_at -= timedelta(minutes=20)
                denied = await recovered.post('/api/account/password', headers=HEADERS,
                                              json={'new_password': PASSWORD})
                assert denied.status_code == 401
                allowed = await recovered.post('/api/account/password', headers=HEADERS, json={
                    'new_password': PASSWORD, 'current_password': NEW_PASSWORD})
                assert allowed.status_code == 200
    asyncio.run(run())


def test_telegram_channel_changes_password_without_current(pg_env):
    async def run():
        async with environment(pg_env) as env:
            tg = await telegram_browser(env)
            async with env.browser() as web:
                await tg.post('/api/account/credentials', headers=HEADERS,
                              json={'login': 'tg_change', 'password': PASSWORD})
                await web.post('/api/account/login', headers=HEADERS,
                               json={'login': 'tg_change', 'password': PASSWORD})
                done = await tg.post('/api/account/password', headers=HEADERS,
                                     json={'new_password': NEW_PASSWORD})
                assert done.status_code == 200
                assert (await tg.get('/api/account/sessions')).status_code == 200   # own session kept
                assert (await web.get('/api/guest/me')).status_code == 401
    asyncio.run(run())


def test_device_list_revoke_and_revoke_others(pg_env):
    async def run():
        async with environment(pg_env) as env:
            async with env.browser(CHROME) as one, env.browser() as two, env.browser() as stranger:
                await one.post('/api/account/register', headers=HEADERS,
                               json={'login': 'devices_1', 'password': PASSWORD})
                await two.post('/api/account/login', headers=HEADERS,
                               json={'login': 'devices_1', 'password': PASSWORD})
                await stranger.post('/api/guest/start', headers=HEADERS)
                mine = (await one.get('/api/account/sessions')).json()['sessions']
                assert len(mine) == 2 and sum(s['current'] for s in mine) == 1
                other = (await stranger.get('/api/account/sessions')).json()['sessions']
                assert len(other) == 1 and other[0]['created_via'] == 'guest'
                assert other[0]['id'] not in {s['id'] for s in mine}
                foreign = await one.post('/api/account/sessions/revoke', headers=HEADERS,
                                         json={'id': other[0]['id']})
                assert foreign.status_code == 404
                assert (await one.post('/api/account/sessions/revoke', headers=HEADERS,
                                       json={'id': 'zzzz'})).status_code == 404
                assert (await stranger.get('/api/guest/me')).status_code == 200
                not_current = next(s for s in mine if not s['current'])
                gone = await one.post('/api/account/sessions/revoke', headers=HEADERS,
                                      json={'id': not_current['id']})
                assert gone.status_code == 200
                assert (await two.get('/api/guest/me')).status_code == 401
                assert len((await one.get('/api/account/sessions')).json()['sessions']) == 1
                async with env.browser() as three:
                    await three.post('/api/account/login', headers=HEADERS,
                                     json={'login': 'devices_1', 'password': PASSWORD})
                    result = await one.post('/api/account/sessions/revoke-others', headers=HEADERS)
                    assert result.status_code == 200 and result.json()['revoked_sessions'] == 1
                    assert (await three.get('/api/guest/me')).status_code == 401
                    assert (await one.get('/api/guest/me')).status_code == 200
    asyncio.run(run())


def test_stale_mini_app_session_needs_the_current_password(pg_env):
    """F8: the telegram channel only gives a passwordless change for a Mini App session younger than 15 minutes."""
    async def run():
        async with environment(pg_env) as env:
            tg = await telegram_browser(env)
            await tg.post('/api/account/credentials', headers=HEADERS,
                          json={'login': 'stale_mini', 'password': PASSWORD})
            async with env.db.transaction() as session:
                for row in (await session.scalars(select(MiniAppSession))).all():
                    row.created_at -= timedelta(minutes=20)
                    row.expires_at += timedelta(minutes=20)
            denied = await tg.post('/api/account/password', headers=HEADERS,
                                   json={'new_password': NEW_PASSWORD})
            assert denied.status_code == 401 and denied.json()['code'] == 'current_password_required'
            wrong = await tg.post('/api/account/password', headers=HEADERS, json={
                'new_password': NEW_PASSWORD, 'current_password': 'not the password'})
            assert wrong.status_code == 401
            ok = await tg.post('/api/account/password', headers=HEADERS, json={
                'new_password': NEW_PASSWORD, 'current_password': PASSWORD})
            assert ok.status_code == 200, ok.text
    asyncio.run(run())


def test_login_race_returns_409_login_taken(pg_env, monkeypatch):
    """F12: a unique-login violation (lost race) is a 409, never a 500."""
    from storage.account_passwords import PasswordAccounts

    async def run():
        async with environment(pg_env) as env:
            first = await telegram_browser(env)
            second = await telegram_browser(env, UID + 1)
            assert (await first.post('/api/account/credentials', headers=HEADERS, json={
                'login': 'race_login', 'password': PASSWORD})).status_code == 200

            async def not_taken(session, login):
                return False
            monkeypatch.setattr(PasswordAccounts, '_taken', staticmethod(not_taken))
            lost = await second.post('/api/account/credentials', headers=HEADERS, json={
                'login': 'race_login', 'password': PASSWORD})
            assert lost.status_code == 409 and lost.json()['code'] == 'login_taken'
            monkeypatch.undo()
            # The failed attempt left the second account usable: it can still choose another login.
            again = await second.post('/api/account/credentials', headers=HEADERS, json={
                'login': 'race_login_2', 'password': PASSWORD})
            assert again.status_code == 200, again.text
    asyncio.run(run())


def test_anonymous_credentials_do_not_run_scrypt_and_tight_paths_are_limited(pg_env, monkeypatch):
    """F10: authenticate before hashing; credentials/merge routes share the tight login bucket."""
    import application.account_security as module
    calls = []
    real = module.hash_password
    monkeypatch.setattr(module, 'hash_password', lambda value: calls.append(1) or real(value))

    async def run():
        async with environment(pg_env) as env:
            def client(host):
                return httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app, client=(host, 1)),
                                         base_url=ORIGIN)
            async with client('127.0.0.21') as anonymous:
                for _ in range(3):
                    response = await anonymous.post('/api/account/credentials', headers=HEADERS,
                                                    json={'login': 'nobody_x', 'password': PASSWORD})
                    assert response.status_code == 401
                response = await anonymous.post('/api/account/password', headers=HEADERS,
                                                json={'new_password': NEW_PASSWORD})
                assert response.status_code == 401
                assert calls == []   # no scrypt for an unauthenticated caller
            for host, path, body in (
                    ('127.0.0.22', '/api/account/credentials', {'login': 'nobody_x', 'password': PASSWORD}),
                    ('127.0.0.23', '/api/account/telegram-login/merge', {}),
                    ('127.0.0.24', '/api/account/telegram-link/merge', {})):
                async with client(host) as limited:
                    codes = [(await limited.post(path, headers=HEADERS, json=body)).status_code
                             for _ in range(12)]
                    assert codes[:10] != [429] * 10 and 429 not in codes[:10], (path, codes)
                    assert codes[10] == 429 and codes[11] == 429, (path, codes)
    asyncio.run(run())


def test_guest_channel_is_closed_in_private_test_even_without_identity_param(pg_env):
    """F10: guest_access() also guards the implicit guest channel (only the mqb_guest cookie)."""
    async def run():
        async with isolated_database(pg_env) as (db, _):
            now = int(time.time())
            app = create_app(database=db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True),
                             clock=lambda: now, allowed_user_ids={UID})
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                client.cookies.set('mqb_guest', 'A' * 43)
                for url in ('/api/account/sessions', '/api/account/sessions?identity=guest'):
                    assert (await client.get(url)).status_code == 403, url
    asyncio.run(run())
