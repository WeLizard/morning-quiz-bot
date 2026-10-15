"""Real HTTP/PG regressions for guest account, room and game lock ordering."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import os
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text

from domain.mafia import new_room_lobby, restart_lobby, set_ready
from storage.admin_actions import operation_fence
from storage.database import normalize_database_url
from storage.games import GameRepository
from storage.guest_accounts import GuestAccounts
from storage.models import Account, Game, GameCommand, GameEvent, GamePlayer, RoomInvite, RoomMembership
from tests.local_database import isolated_database
from web.mini_app import MiniAppSettings, create_app

ORIGIN = 'http://127.0.0.1:4185'
HEADERS = {'Origin': ORIGIN, 'X-Guest-CSRF': '1'}


@pytest.fixture
def pg_url():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL is not configured; no production fallback')
    return normalize_database_url(url)


async def wait_for_blocker(db, waiter, holder):
    for _ in range(150):
        async with db.transaction() as session:
            blockers = await session.scalar(text('SELECT pg_blocking_pids(:pid)'), {'pid': waiter})
        if holder in blockers:
            return
        await asyncio.sleep(.01)
    pytest.fail('HTTP transaction did not wait for the expected PostgreSQL lock')


async def finish_tasks(tasks):
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize('mutation', ['room_join', 'mafia_ready'])
def test_guest_http_mutation_waits_for_restart_without_account_fk_deadlock(pg_url, monkeypatch, mutation):
    async def run():
        async with isolated_database(pg_url) as (db, _):
            app = create_app(database=db, settings=MiniAppSettings('', ORIGIN, offline=True))
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as owner, \
                    httpx.AsyncClient(transport=transport, base_url=ORIGIN) as member:
                owner_id = (await owner.post('/api/guest/start', headers=HEADERS)).json()['account_id']
                member_id = (await member.post('/api/guest/start', headers=HEADERS)).json()['account_id']
                room = await owner.post('/api/guest/rooms', headers=HEADERS,
                    json={'request_id': str(uuid4()), 'title': 'Lock race'})
                assert room.status_code == 200, room.text
                room_id = room.json()['id']
                base = f'/api/guest/rooms/{room_id}'
                invite = (await owner.post(base + '/invites', headers=HEADERS,
                    json={'expires_in_seconds': 3600, 'max_uses': 3})).json()
                joined = await member.post('/api/guest/rooms/join', headers=HEADERS,
                    json={'invite_code': invite['invite_code']})
                assert joined.status_code == 200, joined.text
                membership_version = joined.json()['membership_version']
                finished = new_room_lobby(room_id, owner_id, 'Owner')
                finished['players'].append({'account_id': member_id, 'name': 'Member', 'ready': True})
                finished.update(status='finished', assignments={owner_id: 'mafia', member_id: 'citizen'},
                                alive=[owner_id], winner='mafia', round=1, phase_deadline=None)
                async with db.transaction() as session:
                    old = await GameRepository(session).create_room_current(
                        room_id=room_id, mode='mafia', state=finished)
                    old_id = old.id
                    old_players = [(p.account_id, p.seat, p.status, deepcopy(p.public_state),
                                    deepcopy(p.private_state)) for p in (await session.scalars(
                        select(GamePlayer).where(GamePlayer.game_id == old_id).order_by(GamePlayer.seat))).all()]
                    old_events = [(e.id, e.event_index, e.kind, e.visibility, e.actor_account_id,
                                   e.actor_user_id, deepcopy(e.payload), e.created_at) for e in (await session.scalars(
                        select(GameEvent).where(GameEvent.game_id == old_id).order_by(GameEvent.event_index))).all()]

                locked, release, authenticated = asyncio.Event(), asyncio.Event(), asyncio.Event()
                pids = {}
                create_current = GameRepository.create_room_current
                authorize = GuestAccounts._authorized

                async def paused_create(repo, **kwargs):
                    # room_restart already holds its game advisory lock and Room
                    # row; pause immediately before inserting the new roster FKs.
                    pids['restart'] = await repo.session.scalar(text('SELECT pg_backend_pid()'))
                    locked.set()
                    await asyncio.wait_for(release.wait(), 5)
                    return await create_current(repo, **kwargs)

                async def observed_authorize(store, session, credential, **kwargs):
                    await session.execute(text("SET LOCAL lock_timeout = '5s'"))
                    result = await authorize(store, session, credential, **kwargs)
                    if str(result[0].id) == member_id and kwargs.get('lock'):
                        pids['member'] = await session.scalar(text('SELECT pg_backend_pid()'))
                        authenticated.set()
                    return result

                monkeypatch.setattr(GameRepository, 'create_room_current', paused_create)
                monkeypatch.setattr(GuestAccounts, '_authorized', observed_authorize)
                tasks = []
                try:
                    tasks.append(asyncio.create_task(owner.post(base + '/mafia/restart',
                        headers={**HEADERS, 'Idempotency-Key': 'locking-restart'},
                        json={'expected_revision': 0})))
                    await asyncio.wait_for(locked.wait(), 5)
                    if mutation == 'room_join':
                        tasks.append(asyncio.create_task(member.post('/api/guest/rooms/join', headers=HEADERS,
                            json={'invite_code': invite['invite_code']})))
                    else:
                        tasks.append(asyncio.create_task(member.post(base + '/mafia/lobby/ready',
                            headers={**HEADERS, 'Idempotency-Key': 'locking-ready'},
                            json={'ready': True, 'expected_revision': 1})))
                    await asyncio.wait_for(authenticated.wait(), 5)
                    await wait_for_blocker(db, pids['member'], pids['restart'])
                    release.set()
                    restarted, response = await asyncio.wait_for(asyncio.gather(*tasks), 10)
                    assert restarted.status_code == 200, restarted.text
                    assert response.status_code == 200, response.text
                finally:
                    release.set()
                    await finish_tasks(tasks)

                expected = restart_lobby(finished, room_id=room_id, account_id=owner_id, expected_revision=0)
                if mutation == 'mafia_ready':
                    expected = set_ready(expected, room_id=room_id, account_id=member_id,
                                         ready=True, expected_revision=1)
                    assert response.json()['lobby']['revision'] == 2
                else:
                    assert response.json()['joined'] is False
                    assert response.json()['membership_version'] == membership_version
                async with db.transaction() as session:
                    games = (await session.scalars(select(Game).where(Game.room_id == room_id))).all()
                    assert len(games) == 2
                    retained = await session.get(Game, old_id)
                    assert not retained.is_current and retained.status == 'finished' and retained.state == finished
                    current = next(game for game in games if game.is_current)
                    assert current.id != old_id and current.state == expected and current.status == 'lobby'
                    assert [(p.account_id, p.seat, p.status, p.public_state, p.private_state)
                            for p in (await session.scalars(select(GamePlayer).where(
                                GamePlayer.game_id == old_id).order_by(GamePlayer.seat))).all()] == old_players
                    assert [(e.id, e.event_index, e.kind, e.visibility, e.actor_account_id,
                             e.actor_user_id, e.payload, e.created_at) for e in (await session.scalars(
                        select(GameEvent).where(GameEvent.game_id == old_id).order_by(GameEvent.event_index))).all()] == old_events
                    roster = (await session.scalars(select(GamePlayer).where(
                        GamePlayer.game_id == current.id).order_by(GamePlayer.seat))).all()
                    assert [str(p.account_id) for p in roster] == [owner_id, member_id]
                    assert all(p.user_id is None and p.private_state == {} for p in roster)
                    events = (await session.scalars(select(GameEvent).where(
                        GameEvent.game_id == current.id).order_by(GameEvent.event_index))).all()
                    assert [e.kind for e in events] == (['game_created', 'readiness_changed']
                        if mutation == 'mafia_ready' else ['game_created'])
                    receipts = (await session.scalars(select(GameCommand).order_by(GameCommand.kind))).all()
                    assert [r.kind for r in receipts] == (['mafia.ready', 'mafia.restart']
                        if mutation == 'mafia_ready' else ['mafia.restart'])
                    assert all(r.status == 'completed' for r in receipts)
                    restart_receipt = next(r for r in receipts if r.kind == 'mafia.restart')
                    assert restart_receipt.game_id == old_id
                    assert str(restart_receipt.actor_account_id) == owner_id
                    assert restart_receipt.result == restarted.json()
                    if mutation == 'mafia_ready':
                        ready_receipt = next(r for r in receipts if r.kind == 'mafia.ready')
                        assert ready_receipt.game_id == current.id
                        assert str(ready_receipt.actor_account_id) == member_id
                        assert ready_receipt.result == response.json()['lobby']
                    membership = await session.get(RoomMembership, (room_id, UUID(member_id)))
                    assert membership.status == 'active'
                    assert (await session.get(RoomInvite, invite['id'])).uses == 1
                assert (await member.get('/api/guest/me')).status_code == 200
    asyncio.run(run())


@pytest.mark.parametrize('waiting_operation', ['command', 'logout'])
def test_guest_authorized_preserves_session_serialization_and_logout(pg_url, monkeypatch, waiting_operation):
    async def run():
        async with isolated_database(pg_url) as (db, _):
            store = GuestAccounts(db)
            _, raw = await store.start()
            attempting = asyncio.Event()
            pids = {}
            transaction = db.transaction
            pending = None

            @asynccontextmanager
            async def observed_transaction():
                async with transaction() as session:
                    if asyncio.current_task() is pending:
                        pids['waiter'] = await session.scalar(text('SELECT pg_backend_pid()'))
                        attempting.set()
                    yield session

            async def second_operation():
                if waiting_operation == 'logout':
                    await store.logout(raw)
                    return 'logged out'
                async with store.authorized(raw, lock=True):
                    return 'authorized'

            try:
                async with store.authorized(raw, lock=True) as (session, _, _):
                    holder = await session.scalar(text('SELECT pg_backend_pid()'))
                    monkeypatch.setattr(db, 'transaction', observed_transaction)
                    pending = asyncio.create_task(second_operation())
                    await asyncio.wait_for(attempting.wait(), 5)
                    await wait_for_blocker(db, pids['waiter'], holder)
                assert await asyncio.wait_for(pending, 5) == (
                    'logged out' if waiting_operation == 'logout' else 'authorized')
                if waiting_operation == 'command':
                    await store.logout(raw)
                app = create_app(database=db, settings=MiniAppSettings('', ORIGIN, offline=True))
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                                            cookies={'mqb_guest': raw}) as client:
                    assert (await client.post('/api/guest/rooms', headers=HEADERS,
                        json={'request_id': str(uuid4()), 'title': 'Denied'})).status_code == 401
            finally:
                if pending is not None:
                    await finish_tasks([pending])
    asyncio.run(run())


def test_waiting_guest_http_mutation_obeys_moderation_fence(pg_url, monkeypatch):
    async def run():
        async with isolated_database(pg_url) as (db, _):
            app = create_app(database=db, settings=MiniAppSettings('', ORIGIN, offline=True))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                aid = (await client.post('/api/guest/start', headers=HEADERS)).json()['account_id']
                attempting, pids = asyncio.Event(), {}
                async def observed_fence(session, *, exclusive=False):
                    pids['waiter'] = await session.scalar(text('SELECT pg_backend_pid()'))
                    attempting.set()
                    await operation_fence(session, exclusive=exclusive)
                monkeypatch.setattr('storage.admin_actions.operation_fence', observed_fence)
                pending = None
                try:
                    async with db.transaction() as session:
                        await operation_fence(session, exclusive=True)
                        holder = await session.scalar(text('SELECT pg_backend_pid()'))
                        account = await session.get(Account, UUID(aid))
                        account.bot_blocked = True
                        pending = asyncio.create_task(client.post('/api/guest/rooms', headers=HEADERS,
                            json={'request_id': str(uuid4()), 'title': 'Denied'}))
                        await asyncio.wait_for(attempting.wait(), 5)
                        await wait_for_blocker(db, pids['waiter'], holder)
                    response = await asyncio.wait_for(pending, 5)
                    assert response.status_code == 401, response.text
                    async with db.transaction() as session:
                        assert not (await session.scalars(select(RoomMembership))).all()
                finally:
                    if pending is not None:
                        await finish_tasks([pending])
    asyncio.run(run())
