"""Browser login through Telegram: PostgreSQL + HTTP, bot handler with fake updates.

PG cases accept only tests.local_database's disposable morning_quiz_test URL.
The merge branch (T != C) is covered separately after integration with AccountMergeService.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from handlers.account_login_handlers import AccountLoginHandlers
from qw_farm.integration import register_models
from storage.alchemy import AlchemyService
from storage.models import (Account, AccountIdentity, AlchemyProgress, GuestSession,
                            MiniAppSession, TelegramLoginRequest, User)
from storage.telegram_login import TelegramLogins
from tests.local_database import isolated_database
from tests.test_mini_app import ORIGIN, TOKEN, signed
from tests.test_postgres_members import pg_env  # noqa: F401  (fixture)
from web.client_hint import client_hint
from web.mini_app import MiniAppSettings, create_app

HEADERS = {'Origin': ORIGIN, 'X-Guest-CSRF': '1'}
BASE = '/api/account/telegram-login'
UID, UID2 = 981032000001, 981032000002
CHROME = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
          'Chrome/124.0.0.0 Safari/537.36')


@asynccontextmanager
async def environment(url, monkeypatch, *, allowed_user_ids=None, bot_username='quiz_test_bot'):
    monkeypatch.setenv('QW_FARM_ENABLED', '1')
    register_models()
    async with isolated_database(url) as (db, schema_name):
        import time
        clock = [int(time.time())]
        app = create_app(database=db, allowed_user_ids=allowed_user_ids, clock=lambda: clock[0],
                         settings=MiniAppSettings(TOKEN, ORIGIN, offline=True, bot_username=bot_username))
        transport = httpx.ASGITransport(app=app)
        clients = []

        def new_client():
            client = httpx.AsyncClient(transport=transport, base_url=ORIGIN,
                                       headers={'User-Agent': CHROME})
            clients.append(client)
            return client
        try:
            yield SimpleNamespace(db=db, app=app, clock=clock, new_client=new_client,
                                  logins=TelegramLogins(db, clock=lambda: clock[0]))
        finally:
            for client in clients:
                await client.aclose()


async def begin(client):
    response = await client.post(BASE + '/start', headers=HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    query = parse_qs(urlsplit(body['link']).query)
    token = query['start'][0].removeprefix('login_')
    return body, token


async def complete(client, mode=None):
    return await client.post(BASE + '/complete', headers=HEADERS,
                             json={} if mode is None else {'mode': mode})


def test_client_hint_is_short_and_never_raw():
    assert client_hint(CHROME) == 'Chrome · Windows'
    assert client_hint('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
                       '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1') == 'Safari · iPhone'
    assert client_hint('Mozilla/5.0 (Windows NT 10.0) Chrome/120 Safari/537.36 Edg/120.0') == 'Edge · Windows'
    assert client_hint(None) == client_hint('') == 'Неизвестное устройство'
    assert client_hint('x' * 5000) == 'Неизвестное устройство'
    assert len(client_hint('Chrome/1 ' * 500 + 'Windows')) <= 60


def test_start_requires_bot_username_origin_and_sets_strict_cookie(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch, bot_username='') as env:
            client = env.new_client()
            response = await client.post(BASE + '/start', headers=HEADERS)
            assert response.status_code == 503
        async with environment(pg_env, monkeypatch) as env:
            client = env.new_client()
            assert (await client.post(BASE + '/start')).status_code == 403
            response = await client.post(BASE + '/start', headers=HEADERS)
            assert response.status_code == 200
            body = response.json()
            assert body['link'].startswith('https://t.me/quiz_test_bot?start=login_')
            cookie = response.headers['set-cookie'].lower()
            assert 'mqb_tglogin=' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
            assert 'path=/api/account/telegram-login' in cookie and 'max-age=600' in cookie
            async with env.db.transaction() as session:
                assert 'request_id' not in body  # The browser has no use for the internal id.
                row = await session.scalar(select(TelegramLoginRequest))
                secret = client.cookies.get('mqb_tglogin')
                assert row.client_hint == 'Chrome · Windows' and row.status == 'pending'
                # Only digests are stored.
                assert secret not in (row.browser_secret_hash, row.start_token_hash)
                assert len(row.browser_secret_hash) == 64
    asyncio.run(run())


def test_new_telegram_login_creates_account_and_repeat_is_rejected(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            client = env.new_client()
            body, token = await begin(client)
            assert (await client.get(BASE + '/status')).json()['status'] == 'pending'
            early = await complete(client)
            assert early.status_code == 409 and early.json()['code'] == 'login_pending'
            assert await env.logins.approve(token, UID, 'Тест Игрок') == 'approved'
            status = (await client.get(BASE + '/status')).json()
            assert status['status'] == 'approved' and 'telegram_user_id' not in status
            done = await complete(client)
            assert done.status_code == 200, done.text
            payload = done.json()
            assert payload['result'] == 'logged_in'
            assert payload['profile']['telegram_user_id'] == str(UID)
            assert 'mqb_guest' in done.headers['set-cookie']
            me = await client.get('/api/guest/me')
            assert me.json()['account_id'] == payload['account_id']
            async with env.db.transaction() as session:
                user = await session.get(User, UID)
                assert str(user.account_id) == payload['account_id']
                assert user.display_name == 'Тест Игрок'
                identity = await session.scalar(select(AccountIdentity).where(
                    AccountIdentity.provider == 'telegram', AccountIdentity.provider_subject == str(UID)))
                assert identity.verified_at is not None and str(identity.account_id) == payload['account_id']
                row = await session.scalar(select(GuestSession).where(
                    GuestSession.account_id == UUID(payload['account_id'])))
                assert row.created_via == 'telegram' and row.user_agent == 'Chrome · Windows'
            assert (await client.get(BASE + '/status')).json()['status'] == 'consumed'
            again = await complete(client)
            assert again.status_code == 409 and again.json()['code'] == 'login_used'
            async with env.db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(Account)) == 1
    asyncio.run(run())


def test_existing_telegram_account_is_the_same_as_mini_app(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            mini = env.new_client()
            created = await mini.post('/api/mini/session', json={
                'init_data': signed(UID, date=env.clock[0], query_id=uuid4().hex)})
            assert created.status_code == 200, created.text
            async with env.db.transaction() as session:
                mini_account = (await session.get(User, UID)).account_id
            browser = env.new_client()
            _, token = await begin(browser)
            await env.logins.approve(token, UID, 'Другое имя')
            done = await complete(browser)
            assert done.status_code == 200, done.text
            assert done.json()['result'] == 'logged_in'
            assert done.json()['account_id'] == str(mini_account)
            async with env.db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(Account)) == 1
                assert (await session.get(User, UID)).display_name != 'Другое имя'
    asyncio.run(run())


def test_approve_is_idempotent_exclusive_and_bounded(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            logins = env.logins
            _, token_a, _, _ = await logins.start('Chrome · Windows')
            assert await logins.approve(token_a, UID, 'A') == 'approved'
            assert await logins.approve(token_a, UID, 'A') == 'already'
            assert await logins.approve(token_a, UID2, 'B') == 'taken'
            assert await logins.cancel(token_a, UID2) == 'taken'
            assert await logins.approve('nonexistent-token-nonexistent', UID, 'A') == 'unknown'
            _, token_b, _, _ = await logins.start()
            assert await logins.approve(token_b, UID, 'Bot', is_bot=True) == 'forbidden'
            assert await logins.approve(token_b, 0, 'Zero') == 'forbidden'
            info = await logins.describe(token_b)
            assert info['state'] == 'pending'  # Neither failed attempt changed the request.
            # Expired requests cannot be approved or cancelled.
            env.clock[0] += 601
            assert await logins.approve(token_b, UID, 'A') == 'expired'
            assert await logins.cancel(token_b, UID) == 'expired'
            assert (await logins.describe(token_b))['state'] == 'expired'
    asyncio.run(run())


def test_expired_and_cancelled_requests_cannot_complete(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            client = env.new_client()
            _, token = await begin(client)
            await env.logins.approve(token, UID, 'A')
            env.clock[0] += 601
            assert (await client.get(BASE + '/status')).json()['status'] == 'expired'
            late = await complete(client)
            assert late.status_code == 410 and late.json()['code'] == 'login_expired'
            env.clock[0] += 5
            other = env.new_client()
            _, token2 = await begin(other)
            assert await env.logins.cancel(token2, UID) == 'cancelled'
            assert (await other.get(BASE + '/status')).json()['status'] == 'cancelled'
            denied = await complete(other)
            assert denied.status_code == 410 and denied.json()['code'] == 'login_cancelled'
            assert await env.logins.approve(token2, UID, 'A') == 'cancelled'
            async with env.db.transaction() as session:
                assert await session.get(User, UID) is None
    asyncio.run(run())


def test_foreign_or_missing_browser_cookie_cannot_complete(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            victim = env.new_client()
            _, token = await begin(victim)
            await env.logins.approve(token, UID, 'Victim')
            attacker = env.new_client()
            assert (await complete(attacker)).status_code == 401
            assert (await attacker.get(BASE + '/status')).status_code == 401
            attacker.cookies.set('mqb_tglogin', 'A' * 43)
            assert (await complete(attacker)).status_code == 404
            # The attacker's own request is unapproved: the victim's approval does not transfer.
            attacker.cookies.clear()
            await begin(attacker)
            denied = await complete(attacker)
            assert denied.status_code == 409 and denied.json()['code'] == 'login_pending'
            assert 'mqb_guest' not in denied.headers.get('set-cookie', '')
            # A bad mode and a non-JSON body are rejected before touching the request.
            assert (await complete(victim, 'bogus')).status_code == 400
            assert (await victim.post(BASE + '/complete', headers=HEADERS, content='{}')).status_code == 415
            ok = await complete(victim)
            assert ok.status_code == 200 and ok.json()['result'] == 'logged_in'
            async with env.db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(User)) == 1
    asyncio.run(run())


def test_guest_gets_telegram_linked_and_keeps_progress(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            client = env.new_client()
            started = await client.post('/api/guest/start', headers=HEADERS)
            account_id = started.json()['account_id']
            raw = client.cookies.get('mqb_guest')
            farm = await client.post('/api/farm/v1/start?identity=guest',
                                     headers={'Origin': ORIGIN, 'X-QW-Farm': '1'})
            assert farm.status_code == 200, farm.text
            await AlchemyService(env.db).guest_sync(
                raw, expected_account_id=account_id, discovered=['fire', 'water', 'steam'], attempts=7)
            _, token = await begin(client)
            await env.logins.approve(token, UID, 'Игрок')
            asked = await complete(client)  # F4: auto never links a Telegram to the open profile
            assert asked.status_code == 200, asked.text
            ask = asked.json()
            assert ask['result'] == 'link_required' and ask['account_id'] == account_id
            assert ask['telegram_user_id'] == str(UID) and ask['telegram_display_name'] == 'Игрок'
            assert ask['display_name'] == 'Гость'
            async with env.db.transaction() as session:
                assert await session.get(User, UID) is None  # nothing was linked or created
                assert await session.scalar(select(func.count()).select_from(AccountIdentity)) == 0
                request = await session.scalar(select(TelegramLoginRequest))
                assert request.status == 'approved'  # not consumed: the player may still confirm
            assert (await client.get(BASE + '/status')).json()['status'] == 'approved'
            done = await complete(client, 'link')
            assert done.status_code == 200, done.text
            body = done.json()
            assert body['result'] == 'linked' and body['account_id'] == account_id
            assert body['profile']['telegram_user_id'] == str(UID)
            assert 'mqb_guest' not in done.headers.get('set-cookie', '')  # Same browser session.
            assert (await client.get('/api/guest/me')).json()['account_id'] == account_id
            farm_again = await client.get('/api/farm/v1/me', params={'identity': 'guest'})
            assert farm_again.json()['farm']['id'] == farm.json()['farm']['id']
            async with env.db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(Account)) == 1
                progress = await session.get(AlchemyProgress, UUID(account_id))
                assert progress.user_id == UID and progress.attempts == 7 and 'steam' in progress.discovered
                assert str((await session.get(User, UID)).account_id) == account_id
            assert (await client.get(BASE + '/status')).json()['status'] == 'consumed'
            assert (await complete(client, 'link')).json()['code'] == 'login_used'
            # Proving the same Telegram again is a fresh Telegram sign-in: a new session replaces the old.
            _, token2 = await begin(client)
            await env.logins.approve(token2, UID, 'Игрок')
            again = await complete(client)
            assert again.status_code == 200 and again.json()['result'] == 'already_linked'
            assert 'mqb_guest' in again.headers.get('set-cookie', '')
            assert client.cookies.get('mqb_guest') != raw
            assert (await client.get('/api/guest/me')).json()['account_id'] == account_id
    asyncio.run(run())


def test_browser_with_other_telegram_gets_conflict_then_can_switch(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            client = env.new_client()
            account_id = (await client.post('/api/guest/start', headers=HEADERS)).json()['account_id']
            _, token = await begin(client)
            await env.logins.approve(token, UID, 'Первый')
            assert (await complete(client, 'link')).json()['result'] == 'linked'
            old_cookie = client.cookies.get('mqb_guest')
            _, token2 = await begin(client)
            await env.logins.approve(token2, UID2, 'Второй')
            conflict = await complete(client)
            assert conflict.status_code == 409 and conflict.json()['code'] == 'telegram_other_linked'
            async with env.db.transaction() as session:
                request = (await session.scalars(select(TelegramLoginRequest).where(
                    TelegramLoginRequest.telegram_user_id == UID2))).one()
                assert request.status == 'approved'  # Not consumed: the player may still switch.
                assert await session.get(User, UID2) is None
            switched = await complete(client, 'switch')
            assert switched.status_code == 200, switched.text
            body = switched.json()
            assert body['result'] == 'logged_in' and body['account_id'] != account_id
            assert body['profile']['telegram_user_id'] == str(UID2)
            new_cookie = client.cookies.get('mqb_guest')
            assert new_cookie and new_cookie != old_cookie
            async with env.db.transaction() as session:
                old = await session.scalar(select(GuestSession).where(
                    GuestSession.account_id == UUID(account_id)))
                assert old.revoked is True
                assert str((await session.get(User, UID)).account_id) == account_id  # Untouched.
            client.cookies.set('mqb_guest', old_cookie)
            assert (await client.get('/api/guest/me')).status_code == 401
    asyncio.run(run())


def test_allowed_user_ids_and_blocked_users_are_refused(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch, allowed_user_ids={UID}) as env:
            client = env.new_client()
            _, token = await begin(client)
            await env.logins.approve(token, UID2, 'Чужой')
            denied = await complete(client)
            assert denied.status_code == 403
            async with env.db.transaction() as session:
                assert await session.get(User, UID2) is None
            ok_client = env.new_client()
            _, token2 = await begin(ok_client)
            await env.logins.approve(token2, UID, 'Свой')
            assert (await complete(ok_client)).status_code == 200
            async with env.db.transaction() as session:
                (await session.get(User, UID)).bot_blocked = True
            again = env.new_client()
            _, token3 = await begin(again)
            await env.logins.approve(token3, UID, 'Свой')
            assert (await complete(again)).status_code == 403
    asyncio.run(run())


def test_start_removes_old_requests(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            await env.logins.start()
            env.clock[0] += 3 * 86400
            await env.logins.start()
            async with env.db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(TelegramLoginRequest)) == 1
    asyncio.run(run())


# ---- Bot handler with fake updates -------------------------------------------------------------

class FakeMessage:
    def __init__(self, text=''):
        self.text, self.replies = text, []

    async def reply_text(self, text, reply_markup=None, **kwargs):
        # The bot has Defaults(parse_mode=MarkdownV2): every login message must opt out explicitly.
        assert 'parse_mode' in kwargs and kwargs['parse_mode'] is None, kwargs
        self.replies.append((text, reply_markup))


class FakeChat:
    def __init__(self, chat_id, kind='private'):
        self.id, self.type = chat_id, kind


class FakeQuery:
    def __init__(self, data, chat, user_message_text='x'):
        self.data = data
        self.message = SimpleNamespace(chat=chat)
        self.answers, self.edits = [], []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, **kwargs):
        assert 'parse_mode' in kwargs and kwargs['parse_mode'] is None, kwargs
        self.edits.append(text)


def fake_user(uid, *, is_bot=False, name='Тест Игрок'):
    return SimpleNamespace(id=uid, is_bot=is_bot, full_name=name)


def test_bot_handler_shows_request_and_approves_only_by_button(pg_env, monkeypatch):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            handlers = AccountLoginHandlers(env.db, logins=env.logins)
            registered = handlers.get_handlers()
            assert len(registered) == 2
            _, token, _, _ = await env.logins.start('Chrome · Windows')
            message = FakeMessage(f'/start login_{token}')
            await handlers.start(SimpleNamespace(effective_message=message,
                                                 effective_user=fake_user(UID)), None)
            text, markup = message.replies[0]
            assert 'Chrome · Windows' in text and '(МСК)' in text and 'Отмена' in text
            # F5a: the warning is about a link sent by someone else.
            assert ('Если ссылку тебе прислал кто-то другой — нажми «Отмена»: '
                    'кнопка «Войти» откроет ему твой профиль.') in text
            data = [button.callback_data for button in markup.inline_keyboard[0]]
            assert [d.rsplit(':', 1)[1] for d in data] == ['ok', 'no']
            assert (await env.logins.describe(token))['state'] == 'pending'  # Opening never approves.
            # Unknown link.
            stale = FakeMessage('/start login_' + 'z' * 32)
            await handlers.start(SimpleNamespace(effective_message=stale,
                                                 effective_user=fake_user(UID)), None)
            assert 'устарела' in stale.replies[0][0]
            # A callback outside the user's own private chat is refused.
            group = FakeQuery(data[0], FakeChat(-100123, 'supergroup'))
            await handlers.callback(SimpleNamespace(callback_query=group,
                                                    effective_user=fake_user(UID)), None)
            assert group.answers[0][1] is True and not group.edits
            other_chat = FakeQuery(data[0], FakeChat(UID2))
            await handlers.callback(SimpleNamespace(callback_query=other_chat,
                                                    effective_user=fake_user(UID)), None)
            assert not other_chat.edits
            bot = FakeQuery(data[0], FakeChat(UID))
            await handlers.callback(SimpleNamespace(callback_query=bot,
                                                    effective_user=fake_user(UID, is_bot=True)), None)
            assert not bot.edits and (await env.logins.describe(token))['state'] == 'pending'
            ok = FakeQuery(data[0], FakeChat(UID))
            await handlers.callback(SimpleNamespace(callback_query=ok,
                                                    effective_user=fake_user(UID)), None)
            assert ok.edits == ['Вход подтверждён. Вернись в браузер.']
            repeat = FakeQuery(data[0], FakeChat(UID))
            await handlers.callback(SimpleNamespace(callback_query=repeat,
                                                    effective_user=fake_user(UID)), None)
            assert 'подтверждён' in repeat.edits[0]
            thief = FakeQuery(data[0], FakeChat(UID2))
            await handlers.callback(SimpleNamespace(callback_query=thief,
                                                    effective_user=fake_user(UID2)), None)
            assert 'Не удалось' in thief.edits[0]
            async with env.db.transaction() as session:
                row = await session.scalar(select(TelegramLoginRequest))
                assert row.telegram_user_id == UID and row.status == 'approved'
            # Cancel path on a second request.
            _, token2, _, _ = await env.logins.start()
            info = await env.logins.describe(token2)
            no = FakeQuery(f'qwlogin:{info["id"]}:no', FakeChat(UID))
            await handlers.callback(SimpleNamespace(callback_query=no,
                                                    effective_user=fake_user(UID)), None)
            assert no.edits == ['Вход отменён.']
            assert (await env.logins.describe(token2))['state'] == 'closed'
    asyncio.run(run())


def test_bot_handler_patterns():
    import re
    from handlers.account_login_handlers import CALLBACK_PATTERN, START_PATTERN
    assert re.match(START_PATTERN, '/start login_' + 'a' * 32)
    assert re.match(START_PATTERN, '/start@quiz_bot login_' + 'a_-' * 8)
    assert not re.match(START_PATTERN, '/start login_short')
    assert not re.match(START_PATTERN, '/start something_else')
    assert re.match(CALLBACK_PATTERN, 'qwlogin:' + 'a' * 32 + ':ok')
    assert not re.match(CALLBACK_PATTERN, 'qwlogin:' + 'a' * 32 + ':x')


def test_password_session_becomes_fresh_after_telegram_relogin_of_same_account(pg_env, monkeypatch):
    """F2: C == T used to return without a new session, so recovery without the old password failed."""
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            client = env.new_client()
            reg = await client.post('/api/account/register', headers=HEADERS,
                                    json={'login': 'relogin_user', 'password': 'correct horse battery'})
            assert reg.status_code == 200, reg.text
            first_cookie = client.cookies.get('mqb_guest')
            _, token = await begin(client)
            await env.logins.approve(token, UID, 'Игрок')
            assert (await complete(client)).json()['result'] == 'link_required'
            assert (await complete(client, 'link')).json()['result'] == 'linked'
            # The password session (created_via='password') still needs the current password.
            denied = await client.post('/api/account/password', headers=HEADERS,
                                       json={'new_password': 'another long passphrase'})
            assert denied.status_code == 401 and denied.json()['code'] == 'current_password_required'
            # Prove Telegram again, in the same account: a new session is issued.
            _, token2 = await begin(client)
            await env.logins.approve(token2, UID, 'Игрок')
            again = await complete(client)
            assert again.status_code == 200 and again.json()['result'] == 'already_linked'
            fresh_cookie = client.cookies.get('mqb_guest')
            assert fresh_cookie and fresh_cookie != first_cookie
            async with env.db.transaction() as session:
                rows = (await session.scalars(select(GuestSession))).all()
                old = [r for r in rows if r.created_via == 'password']
                assert old and all(r.revoked for r in old)
                assert [r.created_via for r in rows if not r.revoked] == ['telegram']
            done = await client.post('/api/account/password', headers=HEADERS,
                                     json={'new_password': 'another long passphrase'})
            assert done.status_code == 200, done.text
            other = env.new_client()
            assert (await other.post('/api/account/login', headers=HEADERS, json={
                'login': 'relogin_user', 'password': 'another long passphrase'})).status_code == 200
    asyncio.run(run())


def test_approve_by_id_requires_the_user_the_link_was_shown_to(pg_env, monkeypatch):
    """F14: opening the link records the viewer; only that user can approve through the button id."""
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            logins = env.logins
            _, token, _, _ = await logins.start('Chrome · Windows')
            info = await logins.describe(token)            # no viewer given: nothing recorded
            assert await logins.approve_by_id(info['id'], UID, 'A') == 'forbidden'
            assert (await logins.describe(token, UID))['state'] == 'pending'
            assert await logins.approve_by_id(info['id'], UID2, 'B') == 'forbidden'   # not the viewer
            async with env.db.transaction() as session:
                row = await session.get(TelegramLoginRequest, info['id'])
                assert row.status == 'pending' and row.telegram_user_id == UID
            assert await logins.approve_by_id(info['id'], UID, 'A') == 'approved'
            assert await logins.approve_by_id(info['id'], UID, 'A') == 'already'
            assert await logins.approve_by_id(info['id'], UID2, 'B') == 'taken'
            # A later opener becomes the viewer; the earlier one can no longer approve.
            _, token2, _, _ = await logins.start()
            info2 = await logins.describe(token2, UID)
            await logins.describe(token2, UID2)
            assert await logins.approve_by_id(info2['id'], UID, 'A') == 'forbidden'
            assert await logins.approve_by_id(info2['id'], UID2, 'B') == 'approved'
            # Cancelling stays possible for whoever holds the button.
            _, token3, _, _ = await logins.start()
            info3 = await logins.describe(token3)
            assert await logins.cancel_by_id(info3['id'], UID) == 'cancelled'
    asyncio.run(run())


def test_complete_before_approval_answers_pending_without_locks(pg_env, monkeypatch):
    """F9: a pending request (even one with a recorded viewer) is answered 409 before any advisory lock."""
    from sqlalchemy import event

    async def run():
        async with environment(pg_env, monkeypatch) as env:
            client = env.new_client()
            _, token = await begin(client)
            await env.logins.describe(token, UID)   # the bot showed it; still not approved
            statements = []
            engine = env.db.engine.sync_engine

            def on_execute(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)
            event.listen(engine, 'before_cursor_execute', on_execute)
            try:
                response = await complete(client)
            finally:
                event.remove(engine, 'before_cursor_execute', on_execute)
            assert response.status_code == 409 and response.json()['code'] == 'login_pending'
            assert not any('FOR UPDATE' in text for text in statements)
            # Only the platform fence's advisory lock; no per-Telegram-user lock was taken.
            assert sum('pg_advisory' in text for text in statements) == 1
            async with env.db.transaction() as session:
                assert await session.get(User, UID) is None
    asyncio.run(run())


def test_other_bot_gates_do_not_intercept_login_updates():
    """The group -90 navigation guard must let login updates reach our handlers; ours are registered first."""
    from modules.telegram_menu import navigation_guard

    async def run():
        guard = navigation_guard().callback
        query = SimpleNamespace(data='qwlogin:' + 'a' * 32 + ':ok', message=None)
        # Unknown callback prefixes pass through (no ApplicationHandlerStop).
        assert await guard(SimpleNamespace(callback_query=query), SimpleNamespace(chat_data={})) is None
        # '/start login_...' is a plain message: the guard looks only at callback queries.
        assert await guard(SimpleNamespace(callback_query=None), SimpleNamespace(chat_data={})) is None
    asyncio.run(run())
    source = open('bot.py', encoding='utf-8').read()
    assert source.index('AccountLoginHandlers(') < source.index('common_handlers_instance.get_handlers()')
