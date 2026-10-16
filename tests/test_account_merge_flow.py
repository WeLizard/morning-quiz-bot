"""End-to-end account merge through both Telegram proofs (PostgreSQL + HTTP).

Browser proof: bot-approved login request (cookie mqb_tglogin) -> /telegram-login/complete ->
/telegram-login/merge. Mini App proof: signed initData -> /telegram-link/preview -> /telegram-link/merge.
PG cases accept only tests.local_database's disposable morning_quiz_test URL.
"""
import asyncio
import time
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import re
from sqlalchemy import event, select, update

from qw_farm.integration import register_models
from storage.alchemy import AlchemyService
from storage.models import (Account, AccountIdentity, AccountMerge, AlchemyProgress,
                            GuestSession, TelegramLoginRequest, User)
from storage.telegram_login import TelegramLogins
from tests.local_database import isolated_database
from tests.test_mini_app import ORIGIN, TOKEN, signed
from tests.test_postgres_members import pg_env  # noqa: F401  (fixture)
from web.mini_app import MiniAppSettings, create_app
from web.principal import GUEST_COOKIE, MINI_COOKIE, resolve_principal

HEADERS = {'Origin': ORIGIN, 'X-Guest-CSRF': '1'}
LOGIN = '/api/account/telegram-login'
LINK = '/api/account/telegram-link'
UID, UID2 = 981033000001, 981033000002
CHROME = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
          'Chrome/124.0.0.0 Safari/537.36')


@asynccontextmanager
async def environment(url, monkeypatch):
    monkeypatch.setenv('QW_FARM_ENABLED', '1')
    register_models()
    async with isolated_database(url) as (db, _):
        # Real time: Alchemy services read the wall clock themselves.
        app = create_app(database=db, clock=lambda: int(time.time()),
                         settings=MiniAppSettings(TOKEN, ORIGIN, offline=True, bot_username='quiz_test_bot'))
        clients = []

        def new_client():
            # A distinct client address per browser: the login rate limit is per address.
            transport = httpx.ASGITransport(app=app, client=(f'127.0.0.{len(clients) + 1}', 4000))
            client = httpx.AsyncClient(transport=transport, base_url=ORIGIN, headers={'User-Agent': CHROME})
            clients.append(client)
            return client
        try:
            yield SimpleNamespace(db=db, app=app, new_client=new_client,
                                  logins=TelegramLogins(db, clock=time.time))
        finally:
            for client in clients:
                await client.aclose()


# ------------------------------------------------------------------- helpers
async def guest(env, *, discovered=None, points=None):
    """A browser with a guest session; non-empty when ``discovered`` is given."""
    client = env.new_client()
    started = await client.post('/api/guest/start', headers=HEADERS)
    assert started.status_code == 200, started.text
    account_id = started.json()['account_id']
    if discovered:
        await AlchemyService(env.db).guest_sync(client.cookies.get(GUEST_COOKIE),
                                                expected_account_id=account_id, discovered=discovered)
        if points is not None:
            async with env.db.transaction() as session:
                await session.execute(update(AlchemyProgress).where(
                    AlchemyProgress.account_id == UUID(account_id)).values(points_total=Decimal(points)))
    return client, account_id


async def telegram(env, uid, *, discovered=None, points=0):
    """Telegram account created by a Mini App session; non-empty when ``discovered`` is given."""
    client = env.new_client()
    response = await client.post('/api/mini/session', json={
        'init_data': signed(uid, date=int(time.time()), query_id=uuid4().hex)})
    assert response.status_code == 200, response.text
    async with env.db.transaction() as session:
        account_id = (await session.get(User, uid)).account_id
        if discovered:
            session.add(AlchemyProgress(account_id=account_id, user_id=uid, discovered=list(discovered),
                                        verified_discovered=list(discovered), points_total=Decimal(points)))
    return str(account_id)


async def begin_and_approve(env, client, uid, name='Игрок'):
    response = await client.post(LOGIN + '/start', headers=HEADERS)
    assert response.status_code == 200, response.text
    token = response.json()['link'].split('start=login_', 1)[1]
    request_id = (await env.logins.describe(token, uid))['id']  # the bot shows the request to this user
    assert await env.logins.approve_by_id(request_id, uid, name) == 'approved'
    return request_id


async def complete(client, mode='auto'):
    return await client.post(LOGIN + '/complete', headers=HEADERS, json={'mode': mode})


def merge_body(main, account_id, telegram_account_id):
    return {'main': main, 'account_id': account_id, 'telegram_account_id': telegram_account_id}


async def snapshot(db):
    async with db.transaction() as session:
        return {model.__tablename__: [dict(row) for row in
                (await session.execute(select(model.__table__))).mappings()]
                for model in (Account, User, AccountIdentity, AlchemyProgress, AccountMerge)}


async def resolved_account(env, cookies, identity):
    req = SimpleNamespace(cookies=cookies, query_params={})
    async with resolve_principal(req, database=env.db, guest_store=env.app.state.guest_store,
                                 mini_store=env.app.state.mini_store, identity=identity) as (_, principal):
        return principal.account_id


async def mini_cookie(client, uid):
    client.cookies.clear()
    response = await client.post('/api/mini/session', json={
        'init_data': signed(uid, date=int(time.time()), query_id=uuid4().hex)})
    assert response.status_code == 200, response.text
    return client.cookies.get(MINI_COOKIE)


async def request_status(env, request_id):
    async with env.db.transaction() as session:
        return (await session.get(TelegramLoginRequest, request_id)).status


async def assert_merged(env, secondary_id, main_id, via):
    async with env.db.transaction() as session:
        secondary = await session.get(Account, UUID(secondary_id))
        assert secondary.archived and secondary.merged_into_id == UUID(main_id) and secondary.merged_at
        assert not (await session.get(Account, UUID(main_id))).archived
        audit = await session.scalar(select(AccountMerge).where(
            AccountMerge.merged_account_id == UUID(secondary_id)))
        assert audit is not None and audit.main_account_id == UUID(main_id)
        return audit


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------- tests
def test_browser_both_nonempty_main_current(pg_env, monkeypatch):
    async def case():
        async with environment(pg_env, monkeypatch) as env:
            browser, gid = await guest(env, discovered=['fire', 'steam'], points=5)
            tid = await telegram(env, UID, discovered=['earth', 'lava'], points=99)
            request_id = await begin_and_approve(env, browser, UID)
            done = await complete(browser)
            assert done.status_code == 200, done.text
            body = done.json()
            assert body['result'] == 'merge_required' and body['account_id'] == gid
            assert body['telegram_account_id'] == tid and body['preview']
            assert await request_status(env, request_id) == 'approved'  # not consumed
            before = await snapshot(env.db)
            assert before['account_merges'] == []
            merged = await browser.post(LOGIN + '/merge', headers=HEADERS, json=merge_body('current', gid, tid))
            assert merged.status_code == 200, merged.text
            assert merged.json()['result'] == 'merged' and merged.json()['account_id'] == gid
            assert await request_status(env, request_id) == 'consumed'
            audit = await assert_merged(env, tid, gid, 'player')
            assert audit.initiated_via == 'player'
            # Browser cookie still works and points at main.
            assert (await browser.get('/api/guest/me')).json()['account_id'] == gid
            # Telegram Mini App resolves to the same main account.
            mini = env.new_client()
            await mini_cookie(mini, UID)
            assert await resolved_account(env, {MINI_COOKIE: mini.cookies.get(MINI_COOKIE)}, 'telegram') == gid
            assert (await mini.get('/api/account/sessions', params={'identity': 'telegram'})).status_code == 200
            async with env.db.transaction() as session:
                progress = await session.get(AlchemyProgress, UUID(gid))
                assert {'fire', 'steam', 'earth', 'lava'} <= set(progress.discovered)
                assert progress.points_total == Decimal(5)  # points of main
                assert str((await session.get(User, UID)).account_id) == gid
    run(case())


def test_browser_both_nonempty_main_telegram(pg_env, monkeypatch):
    async def case():
        async with environment(pg_env, monkeypatch) as env:
            browser, gid = await guest(env, discovered=['fire', 'steam'], points=5)
            tid = await telegram(env, UID, discovered=['earth', 'lava'], points=99)
            request_id = await begin_and_approve(env, browser, UID)
            body = (await complete(browser)).json()
            assert body['result'] == 'merge_required'
            merged = await browser.post(LOGIN + '/merge', headers=HEADERS, json=merge_body('telegram', gid, tid))
            assert merged.status_code == 200, merged.text
            assert merged.json()['account_id'] == tid
            assert await request_status(env, request_id) == 'consumed'
            await assert_merged(env, gid, tid, 'player')
            me = await browser.get('/api/guest/me')
            assert me.status_code == 200 and me.json()['account_id'] == tid  # same cookie, now main
            assert await resolved_account(env, {GUEST_COOKIE: browser.cookies.get(GUEST_COOKIE)}, 'guest') == tid
            async with env.db.transaction() as session:
                progress = await session.get(AlchemyProgress, UUID(tid))
                assert {'fire', 'steam', 'earth', 'lava'} <= set(progress.discovered)
                assert progress.points_total == Decimal(99)
                assert (await session.scalar(select(GuestSession).where(
                    GuestSession.account_id == UUID(tid)).limit(1))) is not None
    run(case())


def test_browser_auto_merge_when_one_side_is_empty(pg_env, monkeypatch):
    async def case():
        async with environment(pg_env, monkeypatch) as env:
            # Empty guest, Telegram has progress: main = Telegram.
            browser, gid = await guest(env)
            tid = await telegram(env, UID, discovered=['earth', 'lava'], points=9)
            await begin_and_approve(env, browser, UID)
            done = await complete(browser)
            assert done.status_code == 200, done.text
            # F4: even an automatic merge is a separate confirmed step; complete changes nothing.
            assert done.json()['result'] == 'merge_required' and done.json()['auto'] is True
            assert done.json()['preview']['telegram']['empty'] is False
            async with env.db.transaction() as session:
                assert await session.scalar(select(AccountMerge)) is None
            done = await browser.post(LOGIN + '/merge', headers=HEADERS, json=merge_body('current', gid, tid))
            assert done.status_code == 200, done.text
            assert done.json()['result'] == 'merged' and done.json()['account_id'] == tid
            await assert_merged(env, gid, tid, 'player')
            assert (await browser.get('/api/guest/me')).json()['account_id'] == tid
            # Empty Telegram, guest has progress: main = guest.
            browser2, gid2 = await guest(env, discovered=['fire', 'steam'])
            tid2 = await telegram(env, UID2)
            await begin_and_approve(env, browser2, UID2)
            done2 = await complete(browser2)
            assert done2.status_code == 200, done2.text
            assert done2.json()['result'] == 'merge_required' and done2.json()['auto'] is True
            done2 = await browser2.post(LOGIN + '/merge', headers=HEADERS, json=merge_body('current', gid2, tid2))
            assert done2.status_code == 200, done2.text
            assert done2.json()['result'] == 'merged' and done2.json()['account_id'] == gid2
            await assert_merged(env, tid2, gid2, 'player')
            async with env.db.transaction() as session:
                assert str((await session.get(User, UID2)).account_id) == gid2
    run(case())


def test_repeat_merge_and_complete_are_rejected(pg_env, monkeypatch):
    async def case():
        async with environment(pg_env, monkeypatch) as env:
            browser, gid = await guest(env, discovered=['fire', 'steam'])
            tid = await telegram(env, UID, discovered=['earth', 'lava'])
            await begin_and_approve(env, browser, UID)
            assert (await complete(browser)).json()['result'] == 'merge_required'
            body = merge_body('current', gid, tid)
            assert (await browser.post(LOGIN + '/merge', headers=HEADERS, json=body)).status_code == 200
            after = await snapshot(env.db)
            again = await browser.post(LOGIN + '/merge', headers=HEADERS, json=body)
            assert again.status_code == 409 and again.json()['code'] == 'login_used'
            repeat = await complete(browser)
            assert repeat.status_code == 409 and repeat.json()['code'] == 'login_used'
            assert await snapshot(env.db) == after
    run(case())


def test_foreign_browser_cannot_confirm_and_wrong_ids_change_nothing(pg_env, monkeypatch):
    async def case():
        async with environment(pg_env, monkeypatch) as env:
            victim, gid = await guest(env, discovered=['fire', 'steam'])
            tid = await telegram(env, UID, discovered=['earth', 'lava'])
            await begin_and_approve(env, victim, UID)
            assert (await complete(victim)).json()['result'] == 'merge_required'
            body = merge_body('current', gid, tid)
            # Other browser: its own guest session, no login cookie.
            other = env.new_client()
            await other.post('/api/guest/start', headers=HEADERS)
            before = before_other = await snapshot(env.db)
            assert (await other.post(LOGIN + '/merge', headers=HEADERS, json=body)).status_code == 401
            # ... with its own unapproved request.
            await other.post(LOGIN + '/start', headers=HEADERS)
            denied = await other.post(LOGIN + '/merge', headers=HEADERS, json=body)
            assert denied.status_code == 409 and denied.json()['code'] == 'login_pending'
            # ... with the victim's cookie but without the victim's guest session.
            thief = env.new_client()
            thief.cookies.set('mqb_tglogin', victim.cookies.get('mqb_tglogin'))
            assert (await thief.post(LOGIN + '/merge', headers=HEADERS, json=body)).status_code == 401
            # ... with a forged login cookie.
            forged = env.new_client()
            forged.cookies.set('mqb_tglogin', 'A' * 43)
            assert (await forged.post(LOGIN + '/merge', headers=HEADERS, json=body)).status_code == 404
            assert await snapshot(env.db) == before_other
            # Wrong ids from the right browser: profile_changed, nothing changes.
            for wrong in (merge_body('current', str(uuid4()), tid), merge_body('current', gid, str(uuid4())),
                          merge_body('current', tid, gid)):
                response = await victim.post(LOGIN + '/merge', headers=HEADERS, json=wrong)
                assert response.status_code == 409 and response.json()['code'] == 'profile_changed', response.text
            assert (await victim.post(LOGIN + '/merge', headers=HEADERS,
                                      json=merge_body('both', gid, tid))).status_code == 400
            assert await snapshot(env.db) == before
            # The legitimate confirmation still works afterwards.
            ok = await victim.post(LOGIN + '/merge', headers=HEADERS, json=body)
            assert ok.status_code == 200, ok.text
    run(case())


def test_mini_app_preview_confirm_and_merge(pg_env, monkeypatch):
    async def case():
        async with environment(pg_env, monkeypatch) as env:
            browser, gid = await guest(env, discovered=['fire', 'steam'])
            tid = await telegram(env, UID, discovered=['earth', 'lava'])
            now = int(time.time())
            init = signed(UID, date=now, query_id=uuid4().hex)
            preview = await browser.post(LINK + '/preview', headers=HEADERS, json={'init_data': init})
            assert preview.status_code == 200, preview.text
            data = preview.json()
            assert data['merge_required'] is True and data['auto'] is False
            assert data['account_id'] == gid and data['telegram_account_id'] == tid and data['preview']
            confirm = await browser.post(LINK + '/confirm', headers=HEADERS, json={
                'init_data': signed(UID, date=now, query_id=uuid4().hex), 'confirm': True,
                'account_id': gid, 'telegram_user_id': str(UID)})
            assert confirm.status_code == 409 and confirm.json()['code'] == 'merge_required'
            assert (await snapshot(env.db))['account_merges'] == []
            body = {**merge_body('current', gid, tid), 'init_data': signed(UID, date=now, query_id=uuid4().hex)}
            merged = await browser.post(LINK + '/merge', headers=HEADERS, json=body)
            assert merged.status_code == 200, merged.text
            assert merged.json()['result'] == 'merged' and merged.json()['account_id'] == gid
            await assert_merged(env, tid, gid, 'player')
            after = await snapshot(env.db)
            again = await browser.post(LINK + '/merge', headers=HEADERS, json={
                **body, 'init_data': signed(UID, date=now, query_id=uuid4().hex)})
            assert again.status_code == 409
            assert again.json()['code'] in {'profile_changed', 'merge_unavailable'}
            assert await snapshot(env.db) == after
    run(case())


def test_mini_app_expired_init_data_is_rejected(pg_env, monkeypatch):
    async def case():
        async with environment(pg_env, monkeypatch) as env:
            browser, gid = await guest(env, discovered=['fire', 'steam'])
            tid = await telegram(env, UID, discovered=['earth', 'lava'])
            before = await snapshot(env.db)
            stale = signed(UID, date=int(time.time()) - 400, query_id=uuid4().hex)
            preview = await browser.post(LINK + '/preview', headers=HEADERS, json={'init_data': stale})
            assert preview.status_code == 401
            merged = await browser.post(LINK + '/merge', headers=HEADERS, json={
                **merge_body('current', gid, tid), 'init_data': stale})
            assert merged.status_code == 401
            assert await snapshot(env.db) == before
    run(case())


def test_two_different_telegrams_conflict_then_switch(pg_env, monkeypatch):
    async def case():
        async with environment(pg_env, monkeypatch) as env:
            browser, gid = await guest(env, discovered=['fire', 'steam'])
            await begin_and_approve(env, browser, UID)
            assert (await complete(browser)).json()['result'] == 'link_required'
            assert (await complete(browser, 'link')).json()['result'] == 'linked'
            tid_b = await telegram(env, UID2, discovered=['earth', 'lava'])
            await begin_and_approve(env, browser, UID2, 'Второй')
            before = await snapshot(env.db)
            conflict = await complete(browser)
            assert conflict.status_code == 409 and conflict.json()['code'] == 'telegram_other_linked'
            assert await snapshot(env.db) == before
            switched = await complete(browser, 'switch')
            assert switched.status_code == 200, switched.text
            assert switched.json()['result'] == 'logged_in' and switched.json()['account_id'] == tid_b
            assert (await browser.get('/api/guest/me')).json()['account_id'] == tid_b
            async with env.db.transaction() as session:
                guest_account = await session.get(Account, UUID(gid))
                assert not guest_account.archived and guest_account.merged_into_id is None
                assert str((await session.get(User, UID)).account_id) == gid
                assert (await session.scalar(select(AccountMerge))) is None
    run(case())


def lock_sequence(env):
    """Records the tables of every row-locking SELECT the engine executes, in order."""
    seen = []

    def on_execute(conn, cursor, statement, parameters, context, executemany):
        if re.search(r'FOR (NO KEY )?UPDATE', statement):
            match = re.search(r'FROM (?:\w+\.)?(\w+)', statement)
            if match:
                seen.append(match.group(1))
    engine = env.db.engine.sync_engine
    event.listen(engine, 'before_cursor_execute', on_execute)
    return seen, lambda: event.remove(engine, 'before_cursor_execute', on_execute)


def test_merge_locks_users_identities_sessions_before_accounts(pg_env, monkeypatch):
    """F1/F2: row locks follow the platform order for both choices of the main profile and both proofs."""
    async def case():
        async with environment(pg_env, monkeypatch) as env:
            for index, choice in enumerate(('current', 'telegram', 'mini')):
                uid = UID + 10 * (index + 1)
                browser, gid = await guest(env, discovered=['fire', 'steam'], points=5)
                tid = await telegram(env, uid, discovered=['earth', 'lava'], points=9)
                seen, stop = lock_sequence(env)
                try:
                    if choice == 'mini':
                        init = signed(uid, date=int(time.time()), query_id=uuid4().hex)
                        response = await browser.post(LINK + '/merge', headers=HEADERS, json={
                            **merge_body('telegram', gid, tid), 'init_data': init})
                    else:
                        await begin_and_approve(env, browser, uid)
                        seen.clear()
                        response = await browser.post(LOGIN + '/merge', headers=HEADERS,
                                                      json=merge_body(choice, gid, tid))
                finally:
                    stop()
                assert response.status_code == 200, response.text
                assert 'accounts' in seen and 'users' in seen
                first_account = seen.index('accounts')
                for table in ('users', 'account_identities', 'guest_sessions'):
                    assert table in seen[:first_account], (choice, table, seen)
                    assert table not in seen[first_account:], (choice, table, seen)
                # The Telegram lookup takes the User row before the identity rows.
                assert seen.index('users') < seen.index('account_identities'), seen
    run(case())
