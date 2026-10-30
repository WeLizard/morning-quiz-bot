"""Rooms and room Mafia for the Telegram Mini App channel (one account, any channel)."""
import asyncio
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.engine import make_url
from telegram.error import Forbidden

from application.game_deadlines import GameDeadlineProcessor
from application.mafia import MafiaApplicationService
from application.rooms import RoomApplicationService
from handlers.mafia_handlers import MafiaHandlers, render_room_phase, room_phase_url
from modules.mini_app_launch import startapp_url
from storage.database import normalize_database_url
from storage.models import (Account, AccountIdentity, Game, NotificationOutbox, Room,
                            RoomMembership, User)
from tests.local_database import isolated_database
from tests.test_mini_app import NOW, ORIGIN, TOKEN, signed
from web.mini_app import MiniAppSettings, create_app

TG_USER = 981040000001
BOT = 'MqbTestBot'


@pytest.fixture
def pg_url():
    raw = os.getenv('TEST_DATABASE_URL')
    if not raw:
        pytest.skip('TEST_DATABASE_URL is not configured')
    url = normalize_database_url(raw)
    if make_url(url).database != 'morning_quiz_test':
        pytest.fail('Room channel tests require PostgreSQL morning_quiz_test')
    return url


def hdr(key=None):
    value = {'Origin': ORIGIN, 'X-Guest-CSRF': '1'}
    if key:
        value['Idempotency-Key'] = key
    return value


def new_client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)


async def telegram_client(app, db, uid=TG_USER):
    async with db.transaction() as session:
        account_id = uuid4()
        session.add(Account(id=account_id, display_name='Telegram Player'))
        await session.flush()
        session.add(User(id=uid, account_id=account_id, display_name='Telegram Player'))
    client = new_client(app)
    response = await client.post('/api/mini/session', json={
        'init_data': signed(uid, date=NOW, query_id=uuid4().hex)})
    assert response.status_code == 200, response.text
    assert client.cookies.get('mqb_mini') and not client.cookies.get('mqb_guest')
    return client, str(account_id)


async def guest_client(app):
    client = new_client(app)
    response = await client.post('/api/guest/start', headers=hdr())
    assert response.status_code == 200, response.text
    return client, response.json()['account_id']


@asynccontextmanager
async def environment(url, **settings):
    async with isolated_database(url) as (db, _):
        app = create_app(database=db, clock=lambda: NOW, settings=MiniAppSettings(
            TOKEN, ORIGIN, offline=True, bot_username=BOT, **settings))
        yield db, app


R = '/api/guest/rooms'


async def post(client, path, body, key=None, **params):
    return await client.post(path, json=body, headers=hdr(key), params=params or None)


def test_startapp_url_contract():
    code = 'A' * 43
    assert startapp_url(BOT, 'room_' + code) == f'https://t.me/{BOT}/play?startapp=room_{code}'
    assert startapp_url(BOT, 'room_' + code, '') == f'https://t.me/{BOT}?startapp=room_{code}'
    assert startapp_url('', 'room_x') is None
    assert len('room_' + code) == 48 <= 64
    room_id = str(uuid4())
    assert re.fullmatch(r'roomid_[0-9a-f-]{36}', 'roomid_' + room_id)
    with pytest.raises(ValueError):
        startapp_url(BOT, 'x' * 65)
    with pytest.raises(ValueError):
        startapp_url(BOT, 'bad param')


def test_telegram_and_guests_play_a_full_room_game(pg_url, monkeypatch):
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)

    async def run():
        async with environment(pg_url) as (db, app):
            tg, tg_account = await telegram_client(app, db)
            guests = [await guest_client(app) for _ in range(3)]
            clients = [tg] + [client for client, _ in guests]

            room_id = str(uuid4())
            created = await post(tg, R, {'request_id': room_id, 'title': 'Стол'})
            assert created.status_code == 200 and created.json()['role'] == 'owner'
            again = await post(tg, R, {'request_id': room_id, 'title': 'Стол'})
            assert again.status_code == 200 and again.json()['id'] == room_id

            # Non-owner cannot manage invites; owner gets ready-made links.
            invite = await post(tg, f'{R}/{room_id}/invites', {'expires_in_seconds': 3600, 'max_uses': 5})
            assert invite.status_code == 200
            body = invite.json()
            code = body['invite_code']
            assert body['startapp_param'] == 'room_' + code and len(body['startapp_param']) == 48
            assert body['telegram_url'] == f'https://t.me/{BOT}/play?startapp=room_{code}'
            assert body['web_url'] == f'{ORIGIN}/app#room={code}'
            listed = await tg.get(f'{R}/{room_id}/invites')
            assert listed.status_code == 200 and code not in listed.text
            for client, _ in guests:
                forbidden = await post(client, f'{R}/{room_id}/invites',
                                       {'expires_in_seconds': 3600, 'max_uses': 5})
                assert forbidden.status_code == 404
                joined = await post(client, f'{R}/join', {'invite_code': code})
                assert joined.status_code == 200 and joined.json()['joined'] is True
            assert (await post(tg, f'{R}/{room_id}/leave', {'membership_version': 'x'})).status_code == 403

            lobby_path = f'{R}/{room_id}/mafia/lobby'
            assert (await post(tg, lobby_path, {}, 'tg-lobby-create-1')).status_code == 200
            assert (await post(guests[0][0], lobby_path, {}, 'g0-lobby-create-1')).status_code == 403
            for index, (client, _) in enumerate(guests):
                joined = await post(client, lobby_path + '/join', {}, f'g{index}-join-0001')
                assert joined.status_code == 200 and joined.json()['lobby']['joined']
            replay = await post(tg, lobby_path, {}, 'tg-lobby-create-1')
            assert replay.status_code == 200 and replay.json()['lobby']['is_host']

            async def lobby(client):
                response = await client.get(lobby_path)
                assert response.status_code == 200, response.text
                return response.json()['lobby']

            shared_key = 'shared-ready-key-1'
            for index, client in enumerate(clients):
                current = await lobby(client)
                key = shared_key if index < 2 else f'ready-{index}-0001'  # tg and guest 0 share a key
                ready = await post(client, lobby_path + '/ready',
                                   {'ready': True, 'expected_revision': current['revision']}, key)
                assert ready.status_code == 200, ready.text
                if index == 0:
                    repeat = await post(client, lobby_path + '/ready',
                                        {'ready': True, 'expected_revision': current['revision']}, key)
                    assert repeat.status_code == 200 and repeat.json() == ready.json()
            current = await lobby(tg)
            assert current['can_start']
            started = await post(tg, lobby_path + '/start', {'expected_revision': current['revision']}, 'tg-start-0001')
            assert started.status_code == 200 and started.json()['lobby']['status'] == 'night'

            # Role privacy: each channel sees only its own card, never account ids.
            roles = [(await client.get(f'{R}/{room_id}/mafia/role')).json() for client in clients]
            assert [role['role'] for role in roles] == ['mafia', 'citizen', 'citizen', 'citizen']
            for client in clients[1:]:
                text = (await client.get(lobby_path)).text
                assert 'assignments' not in text and tg_account not in text
                assert '"mafia"' not in text
            assert 'targets' in roles[0] and 'targets' not in roles[1]
            assert roles[0]['teammates'] == [] and 'teammates' not in roles[1]
            night_lobby = await lobby(guests[0][0])
            assert isinstance(night_lobby['server_now'], int)
            assert all('role' not in item and 'voted' not in item for item in night_lobby['players'])

            night = await post(tg, f'{R}/{room_id}/mafia/action',
                               {'expected_revision': roles[0]['phase_revision'], 'target': 'p2'}, 'tg-night-0001')
            assert night.status_code == 200, night.text
            # The only night role acted, yet the night keeps running until its deadline (no early close).
            assert night.json()['lobby']['status'] == 'night'
            from tests.phase_helpers import end_phase
            assert (await end_phase(db, room_id=room_id))['status'] == 'day'
            assert (await post(guests[0][0], f'{R}/{room_id}/mafia/action',
                               {'expected_revision': roles[0]['phase_revision'], 'target': 'p1'},
                               'g0-night-0001')).status_code == 409
            current = await lobby(tg)
            day = night
            talk = await post(guests[1][0], f'{R}/{room_id}/mafia/discussion', {'message': 'Подозреваю p1'}, 'g1-talk-0001')
            assert talk.status_code == 200
            seen = (await tg.get(f'{R}/{room_id}/mafia/discussion')).json()
            assert seen['items'][-1]['message'] == 'Подозреваю p1' and not seen['items'][-1]['is_me']
            current = await lobby(tg)
            voting = await post(tg, f'{R}/{room_id}/mafia/advance', {'expected_revision': current['revision']}, 'tg-adv-0002')
            assert voting.json()['lobby']['status'] == 'voting'
            phase = (await tg.get(f'{R}/{room_id}/mafia/role')).json()['phase_revision']
            before = (await lobby(tg))['players']
            assert [p['voted'] for p in before if p['alive']] == [False, False, False]
            assert 'voted' not in before[1] and all('role' not in p for p in before)
            night_event = [e for e in (await lobby(tg))['history'] if e['type'] == 'night_result'][0]
            assert night_event['eliminated'] == 'p2' and night_event['eliminated_name'] == before[1]['name']
            votes = [(tg, 'p3'), (guests[1][0], 'p1'), (guests[2][0], 'p1')]
            for index, (client, target) in enumerate(votes):
                vote = await post(client, f'{R}/{room_id}/mafia/vote',
                                  {'expected_revision': phase, 'target': target}, f'vote-{index}-0001')
                assert vote.status_code == 200, vote.text
            # The last living player voted: the vote closes early.
            assert vote.json()['lobby']['status'] == 'finished' and vote.json()['lobby']['winner'] == 'citizens'
            for client in clients:
                final = await lobby(client)
                assert final['winner'] == 'citizens'
                assert [p['role'] for p in final['players']] == ['mafia', 'citizen', 'citizen', 'citizen']
                assert [e['eliminated_name'] for e in final['history'] if e['type'] == 'vote_result'] == [final['players'][0]['name']]
            current = await lobby(tg)
            restart = await post(tg, f'{R}/{room_id}/mafia/restart', {'expected_revision': current['revision']}, 'tg-restart-1')
            assert restart.status_code == 200 and restart.json()['lobby']['status'] == 'lobby'

            # Classic/photo and room reads accept the Telegram channel too.
            for path in ('classic/current', 'photo/current'):
                assert (await tg.get(f'{R}/{room_id}/{path}')).status_code == 200
            mine = (await tg.get(R)).json()['items']
            assert [item['id'] for item in mine] == [room_id]
            assert (await tg.get(f'{R}/{room_id}')).status_code == 200
            for client in clients:
                await client.aclose()
    asyncio.run(run())


def test_telegram_member_joins_and_leaves_a_guest_room(pg_url):
    async def run():
        async with environment(pg_url) as (db, app):
            tg, _ = await telegram_client(app, db)
            owner, _ = await guest_client(app)
            room_id = str(uuid4())
            assert (await post(owner, R, {'request_id': room_id, 'title': 'Гостевая'})).status_code == 200
            code = (await post(owner, f'{R}/{room_id}/invites',
                               {'expires_in_seconds': 3600, 'max_uses': 2})).json()['invite_code']
            joined = await post(tg, f'{R}/join', {'invite_code': code})
            assert joined.status_code == 200 and joined.json()['role'] == 'member'
            again = await post(tg, f'{R}/join', {'invite_code': code})
            assert again.status_code == 200 and again.json()['joined'] is False
            left = await post(tg, f'{R}/{room_id}/leave', {'membership_version': joined.json()['membership_version']})
            assert left.status_code == 200 and left.json() == {'left': True}
            assert (await tg.get(f'{R}/{room_id}')).status_code == 404
    asyncio.run(run())


def test_two_cookies_require_explicit_identity_and_select_distinct_accounts(pg_url):
    async def run():
        async with environment(pg_url) as (db, app):
            both, tg_account = await telegram_client(app, db)
            assert (await both.post('/api/guest/start', headers=hdr())).status_code == 200
            assert both.cookies.get('mqb_guest') and both.cookies.get('mqb_mini')
            room_id = str(uuid4())
            body = {'request_id': room_id, 'title': 'Двойной'}
            ambiguous = await post(both, R, body)
            assert ambiguous.status_code == 401 and ambiguous.json()['code'] == 'identity_required'
            assert (await both.get(R)).json()['code'] == 'identity_required'
            assert (await post(both, R, body, identity='bogus')).status_code == 422
            assert (await post(both, R, body, identity='telegram')).status_code == 200
            assert [i['id'] for i in (await both.get(R, params={'identity': 'telegram'})).json()['items']] == [room_id]
            assert (await both.get(R, params={'identity': 'guest'})).json()['items'] == []
            async with db.transaction() as session:
                assert str(await session.scalar(select(Room.owner_account_id).where(Room.id == room_id))) == tg_account
            only_guest, _ = await guest_client(app)
            missing = await only_guest.get(R, params={'identity': 'telegram'})
            assert missing.status_code == 401
    asyncio.run(run())


def test_guest_switch_closes_only_the_guest_channel(pg_url):
    async def run():
        async with environment(pg_url) as (db, app):
            guest, _ = await guest_client(app)
            tg, _ = await telegram_client(app, db)
            both_cookie = guest.cookies.get('mqb_guest')
            restricted = create_app(database=db, clock=lambda: NOW, allowed_user_ids={TG_USER},
                                    settings=MiniAppSettings(TOKEN, ORIGIN, offline=True, bot_username=BOT))
            async with new_client(restricted) as client:
                client.cookies.set('mqb_guest', both_cookie)
                assert (await client.get(R)).status_code == 403
            async with new_client(restricted) as client:
                client.cookies.set('mqb_mini', tg.cookies.get('mqb_mini'))
                assert (await client.get(R)).status_code == 200
                body = {'request_id': str(uuid4()), 'title': 'Закрытый тест'}
                assert (await post(client, R, body)).status_code == 200
    asyncio.run(run())


def _accounts(count):
    return [uuid4() for _ in range(count)]


async def _seed_notification_room(db, monkeypatch):
    """5 players: host (Telegram), linked player, revoked identity, guest-only, blocked user."""
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)
    accounts = _accounts(5)
    users = {0: 9101, 1: 9102, 2: 9103, 4: 9105}
    room_id = str(uuid4())
    now = datetime.now(timezone.utc)
    async with db.transaction() as session:
        session.add_all([Account(id=a, display_name=f'P{i}') for i, a in enumerate(accounts)])
        session.add(Room(id=room_id, kind='standalone', title='Ночной <город>', owner_account_id=accounts[0], state={}))
        session.add_all([RoomMembership(room_id=room_id, account_id=a, role='owner' if i == 0 else 'member',
                                        status='active') for i, a in enumerate(accounts)])
        await session.flush()
        for index, uid in users.items():
            session.add(User(id=uid, account_id=accounts[index], display_name=f'U{index}',
                             bot_blocked=index == 4))
        await session.flush()
        for index, uid in users.items():
            session.add(AccountIdentity(account_id=accounts[index], provider='telegram', provider_subject=str(uid),
                                        verified_at=now, linked_at=now, revoked_at=now if index == 2 else None))
    async with db.transaction() as session:
        service = MafiaApplicationService(session)
        lobby = await service.create_room_lobby(room_id=room_id, account_id=accounts[0], name='P0', command_id='n-create-0001')
        for index, account in enumerate(accounts[1:], 1):
            lobby = await service.room_join(room_id=room_id, account_id=account, name=f'P{index}', command_id=f'n-join-{index:04d}')
        for index, account in enumerate(accounts):
            lobby = await service.room_ready(room_id=room_id, account_id=account, ready=True,
                                             expected_revision=lobby['revision'], command_id=f'n-ready-{index:04d}')
    return room_id, accounts, lobby


async def _outbox(db):
    async with db.transaction() as session:
        return (await session.scalars(select(NotificationOutbox).where(
            NotificationOutbox.kind == 'mafia.room_phase').order_by(NotificationOutbox.dedupe_key))).all()


def test_room_phase_notifications_go_to_linked_players_without_secrets(pg_url, monkeypatch):
    async def run():
        async with isolated_database(pg_url) as (db, _):
            room_id, accounts, lobby = await _seed_notification_room(db, monkeypatch)
            assert await _outbox(db) == []
            async with db.transaction() as session:
                started = await MafiaApplicationService(session).room_start(
                    room_id=room_id, account_id=accounts[0], expected_revision=lobby['revision'], command_id='n-start-0001')
            rows = await _outbox(db)
            # Host is the actor (skipped); revoked identity, guest-only and blocked user get nothing.
            assert [(row.user_id, row.chat_id) for row in rows] == [(9102, 9102)]
            payload = rows[0].payload
            assert payload['status'] == 'night' and payload['room_id'] == room_id
            assert set(payload) == {'room_id', 'room_title', 'status', 'round', 'phase_revision'}
            assert 'assignments' not in str(payload) and 'role' not in str(payload)

            async with db.transaction() as session:  # replayed command: cached, no second nudge
                again = await MafiaApplicationService(session).room_start(
                    room_id=room_id, account_id=accounts[0], expected_revision=lobby['revision'], command_id='n-start-0001')
                assert again == started
            assert len(await _outbox(db)) == 1

            deadline = datetime.fromtimestamp(started['ends_at'], tz=timezone.utc)
            assert (await GameDeadlineProcessor(db).run_once(now=deadline))['mafia'] == 1
            await GameDeadlineProcessor(db).run_once(now=deadline)
            rows = await _outbox(db)
            day = [row for row in rows if row.payload['status'] == 'day']
            assert sorted(row.user_id for row in day) == [9101, 9102]  # deadline: nobody is the actor
            assert len(rows) == 3

            group = await _outbox_all_other_kinds(db)
            assert group == 0
    asyncio.run(run())


async def _outbox_all_other_kinds(db):
    async with db.transaction() as session:
        return len((await session.scalars(select(NotificationOutbox).where(
            NotificationOutbox.kind == 'mafia.phase'))).all())


def test_room_phase_delivery_renders_button_skips_forbidden_and_stale(pg_url, monkeypatch):
    monkeypatch.delenv('MINI_APP_SHORT_NAME', raising=False)

    async def run():
        async with isolated_database(pg_url) as (db, _):
            room_id, accounts, lobby = await _seed_notification_room(db, monkeypatch)
            async with db.transaction() as session:
                started = await MafiaApplicationService(session).room_start(
                    room_id=room_id, account_id=accounts[0], expected_revision=lobby['revision'], command_id='n-start-0002')
            bot = SimpleNamespace(username=BOT, send_message=AsyncMock())
            await MafiaHandlers(db)._deliver_notifications(SimpleNamespace(bot=bot))
            bot.send_message.assert_awaited_once()
            args, kwargs = bot.send_message.await_args.args, bot.send_message.await_args.kwargs
            assert args[0] == 9102 and 'Ночной город' in args[1] and '&lt;город&gt;' in args[1]
            assert 'наступила ночь' in args[1] and 'мафия' not in args[1].lower()
            button = kwargs['reply_markup'].inline_keyboard[0][0]
            assert button.url == f'https://t.me/{BOT}/play?startapp=roomid_{room_id}'
            assert len(button.url.split('startapp=')[1]) <= 64
            assert [row.status for row in await _outbox(db)] == ['delivered']

            # Deadline -> day for 9101 and 9102; Telegram refuses (bot never started): quiet skip.
            deadline = datetime.fromtimestamp(started['ends_at'], tz=timezone.utc)
            await GameDeadlineProcessor(db).run_once(now=deadline)
            blocked = SimpleNamespace(username=BOT, send_message=AsyncMock(side_effect=Forbidden('cannot initiate')))
            await MafiaHandlers(db)._deliver_notifications(SimpleNamespace(bot=blocked))
            assert blocked.send_message.await_count == 2
            rows = await _outbox(db)
            assert sorted(row.status for row in rows) == ['delivered', 'skipped', 'skipped']

            # Superseded phase: a queued nudge is dropped at delivery time.
            async with db.transaction() as session:
                game = await session.scalar(select(Game).where(Game.room_id == room_id, Game.is_current.is_(True)))
                await MafiaApplicationService(session)._notify_room_phase(
                    game, dict(game.state, status='voting', phase_revision=game.state['phase_revision'] + 1))
            await MafiaHandlers(db)._deliver_notifications(SimpleNamespace(bot=bot))
            assert bot.send_message.await_count == 1
            assert sorted(row.status for row in await _outbox(db)) == ['delivered'] + ['skipped'] * 4
    asyncio.run(run())


def test_room_phase_rendering_and_switch(monkeypatch):
    for status, word in (('night', 'ночь'), ('day', 'день'), ('voting', 'голосование'), ('finished', 'завершена')):
        text, rows = render_room_phase({'status': status, 'room_title': 'X'}, url='https://t.me/b/p?startapp=roomid_1')
        assert word in text and rows[0][0].url.endswith('roomid_1')
    assert render_room_phase({'status': 'lobby'}) is None
    assert render_room_phase({'status': 'night', 'room_title': 'X'})[1] == []
    assert room_phase_url('', 'abc') is None
    from storage.notifications import NotificationQueue
    for flag, present in (('0', False), ('1', True)):
        monkeypatch.setenv('MQB_ROOM_MAFIA_DELIVERY_ENABLED', flag)
        claim = AsyncMock(return_value=None)
        monkeypatch.setattr(NotificationQueue, 'claim', claim)
        asyncio.run(MafiaHandlers(object())._deliver_notifications(SimpleNamespace(bot=SimpleNamespace())))
        assert ('mafia.room_phase' in claim.await_args.kwargs['kinds']) is present
