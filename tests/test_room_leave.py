"""Standalone room leave: real PostgreSQL, HTTP boundaries and lock races."""
import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, text

from application.mafia import MafiaApplicationService
from application.rooms import RoomApplicationService
from domain.mafia import new_room_lobby
from storage.games import GameRepository
from storage.models import Account, Game, GamePlayer, Room, RoomMembership
from tests.local_database import isolated_database
from tests.test_postgres_members import pg_env
from web.mini_app import MiniAppSettings, create_app

ORIGIN = 'http://127.0.0.1:4185'
HEADERS = {'Origin': ORIGIN, 'X-Guest-CSRF': '1'}


async def seed_room(db):
    owner, member, outsider = uuid4(), uuid4(), uuid4()
    room_id = str(uuid4())
    async with db.transaction() as session:
        session.add_all([Account(id=value, display_name='Игрок')
                         for value in (owner, member, outsider)])
    async with db.transaction() as session:
        service = RoomApplicationService(session)
        await service.create(account_id=owner, request_id=room_id, title='Компания')
        invite = await service.create_invite(account_id=owner, room_id=room_id,
                                             expires_in_seconds=3600, max_uses=5)
        joined = await service.join_by_invite(account_id=member, invite_code=invite['invite_code'])
    return room_id, owner, member, outsider, invite['invite_code'], joined['membership_version']


def test_room_leave_replay_rejoin_stale_version_and_history(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            room_id, owner, member, outsider, code, version = await seed_room(db)
            async with db.transaction() as session:
                service = RoomApplicationService(session)
                with pytest.raises(PermissionError):
                    await service.leave(account_id=owner, room_id=room_id, membership_version=version)
                for aid, rid in ((outsider, room_id), (member, 'unknown')):
                    with pytest.raises(LookupError):
                        await service.leave(account_id=aid, room_id=rid, membership_version=version)
                game = Game(id=str(uuid4()), room_id=room_id, mode='classic', status='finished',
                            phase='finished', revision=0, is_current=True, state={'history': ['answer']})
                session.add(game)
                await session.flush()
                session.add(GamePlayer(game_id=game.id, account_id=member, seat='1', status='active',
                                       public_state={'score': '5'}))
                await session.flush()
                assert await service.leave(account_id=member, room_id=room_id,
                                           membership_version=version) == {'left': True}
                assert await service.leave(account_id=member, room_id=room_id,
                                           membership_version=version) == {'left': False}
                assert await service.list_mine(account_id=member) == []
                with pytest.raises(LookupError):
                    await service.get_mine(account_id=member, room_id=room_id)
                assert (await session.get(RoomMembership, (room_id, member))).status == 'inactive'
                assert game.state == {'history': ['answer']}
                assert await session.scalar(select(func.count()).select_from(GamePlayer)) == 1
                returned = await service.join_by_invite(account_id=member, invite_code=code)
                assert returned['joined'] and returned['membership_version'] != version
                with pytest.raises(RuntimeError, match='изменилось'):
                    await service.leave(account_id=member, room_id=room_id, membership_version=version)
                assert (await service.get_mine(account_id=member, room_id=room_id)) == {
                    key: value for key, value in returned.items() if key != 'joined'}
                assert await service.leave(account_id=member, room_id=room_id,
                                           membership_version=returned['membership_version']) == {'left': True}
                assert await session.scalar(select(func.count()).select_from(Account)) == 3
    asyncio.run(run())


@pytest.mark.parametrize('mode,status', [('classic', 'active'), ('photo', 'active'),
                                        ('mafia', 'lobby'), ('mafia', 'night'),
                                        ('mafia', 'day'), ('mafia', 'voting')])
def test_room_leave_blocks_any_current_nonterminal_game(pg_env, mode, status):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            room_id, _, member, _, _, version = await seed_room(db)
            async with db.transaction() as session:
                session.add(Game(id=str(uuid4()), room_id=room_id, mode=mode, status=status,
                                 phase=status, revision=0, is_current=True, state={}))
                await session.flush()
                with pytest.raises(RuntimeError, match='незавершённая'):
                    await RoomApplicationService(session).leave(
                        account_id=member, room_id=room_id, membership_version=version)
                assert (await session.get(RoomMembership, (room_id, member))).status == 'active'
    asyncio.run(run())


@pytest.mark.parametrize('status', ['finished', 'stopped', 'interrupted'])
def test_room_leave_allows_terminal_games_and_ignores_old_active_history(pg_env, status):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            room_id, _, member, _, _, version = await seed_room(db)
            async with db.transaction() as session:
                for mode in ('classic', 'mafia', 'photo'):
                    session.add_all([
                        Game(id=str(uuid4()), room_id=room_id, mode=mode, status=status,
                             phase=status, revision=0, is_current=True, state={}),
                        Game(id=str(uuid4()), room_id=room_id, mode=mode, status='active',
                             phase='active', revision=0, is_current=False, state={}),
                    ])
            async with db.transaction() as session:
                assert await RoomApplicationService(session).leave(account_id=member, room_id=room_id,
                    membership_version=version) == {'left': True}
                assert await session.scalar(select(func.count()).select_from(Game)) == 6
    asyncio.run(run())


def test_concurrent_leave_is_once_and_waiting_stale_leave_cannot_undo_rejoin(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            room_id, _, member, _, code, version = await seed_room(db)
            async def leave_once():
                async with db.transaction() as session:
                    return await RoomApplicationService(session).leave(account_id=member, room_id=room_id,
                                                                        membership_version=version)
            results = await asyncio.wait_for(asyncio.gather(leave_once(), leave_once()), 8)
            assert sorted(result['left'] for result in results) == [False, True]
            joining, release, attempting = asyncio.Event(), asyncio.Event(), asyncio.Event()
            async def rejoin():
                async with db.transaction() as session:
                    returned = await RoomApplicationService(session).join_by_invite(
                        account_id=member, invite_code=code)
                    joining.set()
                    await release.wait()
                    return returned
            async def stale_leave():
                await joining.wait()
                async with db.transaction() as session:
                    await session.execute(text("SET LOCAL lock_timeout = '5s'"))
                    attempting.set()
                    with pytest.raises(RuntimeError, match='изменилось'):
                        await RoomApplicationService(session).leave(account_id=member, room_id=room_id,
                                                                    membership_version=version)
            joiner, leaver = asyncio.create_task(rejoin()), asyncio.create_task(stale_leave())
            await attempting.wait()
            # The rejoin has applied in its transaction and holds Room; the
            # stale transaction must re-read membership after this commits.
            release.set()
            returned, _ = await asyncio.wait_for(asyncio.gather(joiner, leaver), 8)
            async with db.transaction() as session:
                assert (await RoomApplicationService(session).get_mine(
                    account_id=member, room_id=room_id))['membership_version'] == returned['membership_version']
    asyncio.run(run())


def test_mafia_restart_filters_left_members_but_retains_finished_roster(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            room_id, owner, member, _, _, version = await seed_room(db)
            async with db.transaction() as session:
                state = new_room_lobby(room_id, str(owner), 'Владелец')
                state['players'].append({'account_id': str(member), 'name': 'Участник', 'ready': True})
                state.update(status='finished', assignments={str(owner): 'mafia', str(member): 'citizen'},
                             alive=[str(owner)], winner='mafia', round=1, phase_deadline=None)
                old = await GameRepository(session).create_room_current(room_id=room_id, mode='mafia', state=state)
                old_id = old.id
                await RoomApplicationService(session).leave(account_id=member, room_id=room_id,
                                                            membership_version=version)
                result = await MafiaApplicationService(session).room_restart(
                    room_id=room_id, account_id=owner, expected_revision=0,
                    command_id='restart-with-left-member')
                assert result['lobby']['status'] == 'lobby'
                current = await GameRepository(session).current_in_room(room_id=room_id, mode='mafia')
                assert [p['account_id'] for p in current.state['players']] == [str(owner)]
                retained = await session.get(Game, old_id)
                assert not retained.is_current and len(retained.state['players']) == 2
                assert await session.scalar(select(func.count()).select_from(GamePlayer).where(
                    GamePlayer.game_id == old_id)) == 2
    asyncio.run(run())


@pytest.mark.parametrize('first', ['leave', 'restart'])
def test_room_leave_and_mafia_restart_race_both_orders(pg_env, first):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            room_id, owner, member, _, _, version = await seed_room(db)
            async with db.transaction() as session:
                state = new_room_lobby(room_id, str(owner), 'Владелец')
                state['players'].append({'account_id': str(member), 'name': 'Участник', 'ready': True})
                state.update(status='finished', assignments={str(owner): 'mafia', str(member): 'citizen'},
                             alive=[str(owner)], winner='mafia', round=1, phase_deadline=None)
                old = await GameRepository(session).create_room_current(room_id=room_id, mode='mafia', state=state)
                old_id = old.id
            locked, release, attempting = asyncio.Event(), asyncio.Event(), asyncio.Event()
            waiting_pid = []

            async def command(session, kind):
                if kind == 'leave':
                    return await RoomApplicationService(session).leave(
                        account_id=member, room_id=room_id, membership_version=version)
                return await MafiaApplicationService(session).room_restart(
                    room_id=room_id, account_id=owner, expected_revision=0,
                    command_id='restart-racing-leave')

            async def run_first():
                async with db.transaction() as session:
                    result = await command(session, first)
                    locked.set()
                    await release.wait()
                    return result

            async def run_second():
                await locked.wait()
                async with db.transaction() as session:
                    await session.execute(text("SET LOCAL lock_timeout = '5s'"))
                    waiting_pid.append(await session.scalar(text('SELECT pg_backend_pid()')))
                    attempting.set()
                    if first == 'restart':
                        with pytest.raises(RuntimeError, match='незавершённая'):
                            await command(session, 'leave')
                        return {'blocked': True}
                    return await command(session, 'restart')

            holder, waiter = asyncio.create_task(run_first()), asyncio.create_task(run_second())
            await attempting.wait()
            observed_wait = False
            try:
                for _ in range(100):
                    async with db.transaction() as session:
                        observed_wait = await session.scalar(text(
                            "SELECT wait_event = 'advisory' FROM pg_stat_activity WHERE pid = :pid"),
                            {'pid': waiting_pid[0]})
                    if observed_wait:
                        break
                    await asyncio.sleep(.01)
            finally:
                release.set()
            results = await asyncio.wait_for(asyncio.gather(holder, waiter), 8)
            assert observed_wait, 'second command must wait for the first transaction game lock'
            async with db.transaction() as session:
                current = await GameRepository(session).current_in_room(room_id=room_id, mode='mafia')
                assert current.status == 'lobby' and current.id != old_id
                expected_roster = [str(owner)] if first == 'leave' else [str(owner), str(member)]
                assert [p['account_id'] for p in current.state['players']] == expected_roster
                assert (await session.get(RoomMembership, (room_id, member))).status == (
                    'inactive' if first == 'leave' else 'active')
                retained = await session.get(Game, old_id)
                assert retained.status == 'finished' and not retained.is_current
                assert [p['account_id'] for p in retained.state['players']] == [str(owner), str(member)]
                assert await session.scalar(select(func.count()).select_from(GamePlayer).where(
                    GamePlayer.game_id == old_id)) == 2
                if first == 'restart':
                    assert results[1] == {'blocked': True}
                else:
                    assert results[0] == {'left': True}
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['classic', 'mafia', 'photo'])
def test_room_leave_waits_for_first_start_and_observes_committed_game(pg_env, mode):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            room_id, _, member, _, _, version = await seed_room(db)
            locked, release, attempting = asyncio.Event(), asyncio.Event(), asyncio.Event()
            async def start():
                async with db.transaction() as session:
                    repo = GameRepository(session)
                    assert await repo.current_in_room(room_id=room_id, mode=mode, lock=True) is None
                    locked.set()
                    await release.wait()
                    session.add(Game(id=str(uuid4()), room_id=room_id, mode=mode,
                                     status='lobby' if mode == 'mafia' else 'active', phase='active',
                                     revision=0, is_current=True, state={}))
            async def leave():
                await locked.wait()
                async with db.transaction() as session:
                    await session.execute(text("SET LOCAL lock_timeout = '5s'"))
                    attempting.set()
                    with pytest.raises(RuntimeError, match='незавершённая'):
                        await RoomApplicationService(session).leave(account_id=member, room_id=room_id,
                                                                    membership_version=version)
            starter, leaver = asyncio.create_task(start()), asyncio.create_task(leave())
            await attempting.wait()
            # Check actual PG wait, not scheduler timing.
            for _ in range(100):
                async with db.transaction() as session:
                    waiting = await session.scalar(text("SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND wait_event = 'advisory'"))
                if waiting:
                    break
                await asyncio.sleep(.01)
            else:
                release.set()
                await asyncio.gather(starter, leaver)
                pytest.fail('leave did not wait on the game advisory key')
            release.set()
            await asyncio.wait_for(asyncio.gather(starter, leaver), 8)
            async with db.transaction() as session:
                assert (await session.get(RoomMembership, (room_id, member))).status == 'active'
    asyncio.run(run())


def test_room_leave_http_contract_and_revoked_invite(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            app = create_app(database=db, settings=MiniAppSettings('', ORIGIN, offline=True))
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as owner, \
                    httpx.AsyncClient(transport=transport, base_url=ORIGIN) as member, \
                    httpx.AsyncClient(transport=transport, base_url=ORIGIN) as outsider:
                for client in (owner, member, outsider):
                    assert (await client.post('/api/guest/start', headers=HEADERS)).status_code == 200
                created = (await owner.post('/api/guest/rooms', headers=HEADERS,
                    json={'request_id': str(uuid4()), 'title': 'Компания'})).json()
                room_id = created['id']
                base = f'/api/guest/rooms/{room_id}'
                invite = (await owner.post(base + '/invites', headers=HEADERS,
                    json={'expires_in_seconds': 3600, 'max_uses': 5})).json()
                joined = (await member.post('/api/guest/rooms/join', headers=HEADERS,
                    json={'invite_code': invite['invite_code']})).json()
                payload = {'membership_version': joined['membership_version']}
                assert (await owner.post(base + '/leave', headers=HEADERS, json=payload)).status_code == 403
                assert (await outsider.post(base + '/leave', headers=HEADERS, json=payload)).status_code == 404
                for headers in ({}, {'Origin': ORIGIN}, {'Origin': 'https://evil.example', 'X-Guest-CSRF': '1'}):
                    assert (await member.post(base + '/leave', headers=headers, json=payload)).status_code == 403
                for invalid in ({}, {**payload, 'account_id': str(uuid4())}, {'membership_version': 1}):
                    assert (await member.post(base + '/leave', headers=HEADERS, json=invalid)).status_code == 400
                assert (await member.post(base + '/leave', headers=HEADERS, content='text')).status_code == 415
                assert (await member.post(base + '/leave', headers=HEADERS, json=payload)).json() == {'left': True}
                assert (await member.post(base + '/leave', headers=HEADERS, json=payload)).json() == {'left': False}
                assert (await member.get(base)).status_code == 404
                assert (await member.get('/api/guest/rooms')).json() == {'items': []}
                assert (await owner.delete(base + '/invites/' + invite['id'], headers=HEADERS)).status_code == 204
                assert (await member.post('/api/guest/rooms/join', headers=HEADERS,
                    json={'invite_code': invite['invite_code']})).status_code == 404
                fresh = (await owner.post(base + '/invites', headers=HEADERS,
                    json={'expires_in_seconds': 3600, 'max_uses': 5})).json()
                returned = (await member.post('/api/guest/rooms/join', headers=HEADERS,
                    json={'invite_code': fresh['invite_code']})).json()
                assert returned['membership_version'] != payload['membership_version']
                assert (await member.post(base + '/leave', headers=HEADERS, json=payload)).status_code == 409
                assert (await member.get(base)).status_code == 200
                async with db.transaction() as session:
                    session.add(Game(id=str(uuid4()), room_id=room_id, mode='mafia', status='lobby',
                                     phase='lobby', revision=0, is_current=True, state={}))
                assert (await member.post(base + '/leave', headers=HEADERS,
                    json={'membership_version': returned['membership_version']})).status_code == 409
    asyncio.run(run())
