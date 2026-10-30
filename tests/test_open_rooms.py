"""PostgreSQL tests: open rooms, waiting list, removal, short invite codes, limits, early close."""
import asyncio
import itertools
import os
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.engine import make_url

from application import room_limits
from application.mafia import MafiaApplicationService
from application.rooms import (OPEN_ROOM_IDLE, InviteRejected, RoomApplicationService,
                               RoomRateLimited)
from domain.mafia import TableFull
from storage.database import normalize_database_url
from storage.models import (Account, GameEvent, NotificationOutbox, Room, RoomInvite,
                            RoomJoinAttempt, RoomMembership)
from tests.local_database import isolated_database

COUNTER = itertools.count(1)


def cid(label='c'):
    return f'{label}-{next(COUNTER):06d}-{uuid4().hex[:6]}'


@pytest.fixture
def pg_url():
    raw = os.getenv('TEST_DATABASE_URL')
    if not raw:
        pytest.skip('TEST_DATABASE_URL is not configured')
    url = normalize_database_url(raw)
    if make_url(url).database != 'morning_quiz_test':
        pytest.fail('Open room tests require PostgreSQL morning_quiz_test')
    return url


async def make_accounts(db, count, prefix='P'):
    ids = [uuid4() for _ in range(count)]
    async with db.transaction() as session:
        session.add_all([Account(id=a, display_name=f'{prefix}{i}') for i, a in enumerate(ids)])
    return ids


async def make_room(db, owner, title='Ночной стол', *, open_room=True, now=None):
    room_id = str(uuid4())
    async with db.transaction() as session:
        await RoomApplicationService(session).create(account_id=owner, request_id=room_id, title=title)
        await MafiaApplicationService(session).create_room_lobby(
            room_id=room_id, account_id=owner, name='Хозяин', command_id=cid('create'))
        if open_room:
            await RoomApplicationService(session).set_open(
                account_id=owner, room_id=room_id, open=True, now=now)
    return room_id


async def join_open(db, room_id, account, name='Гость', now=None):
    async with db.transaction() as session:
        return await MafiaApplicationService(session).room_join_open(
            room_id=room_id, account_id=account, name=name, command_id=cid('open'), now=now)


async def mafia(db, method, **kwargs):
    async with db.transaction() as session:
        return await getattr(MafiaApplicationService(session), method)(command_id=cid(method), **kwargs)


async def lobby_of(db, room_id, account):
    async with db.transaction() as session:
        return await MafiaApplicationService(session).room_lobby(room_id=room_id, account_id=account)


async def ready_all(db, room_id, accounts):
    for account in accounts:
        lobby = await lobby_of(db, room_id, account)
        await mafia(db, 'room_ready', room_id=room_id, account_id=account, ready=True,
                    expected_revision=lobby['revision'])
    return await lobby_of(db, room_id, accounts[0])


async def end_phase(db, room_id):
    """What the deadline worker does: advance the due phase. The night never closes any other way."""
    from storage.models import Game
    async with db.transaction() as session:
        game_id = await session.scalar(select(Game.id).where(
            Game.room_id == room_id, Game.mode == 'mafia', Game.is_current.is_(True)))
    async with db.transaction() as session:
        return await MafiaApplicationService(session).advance_due_game(
            game_id=game_id, now=datetime.now(timezone.utc) + timedelta(hours=1))


def test_open_toggle_list_privacy_and_idle_expiry(pg_url):
    async def run():
        async with isolated_database(pg_url) as (db, _):
            owner, stranger = await make_accounts(db, 2)
            room_id = await make_room(db, owner, open_room=False)
            async with db.transaction() as session:
                rooms = RoomApplicationService(session)
                assert await rooms.list_open(account_id=stranger) == []  # closed by default
                assert (await rooms.get_mine(account_id=owner, room_id=room_id))['open'] is False
                with pytest.raises(LookupError):
                    await rooms.set_open(account_id=stranger, room_id=room_id, open=True)
                with pytest.raises(ValueError):
                    await rooms.set_open(account_id=owner, room_id=room_id, open='yes')
            t0 = datetime.now(timezone.utc)
            async with db.transaction() as session:
                opened = await RoomApplicationService(session).set_open(
                    account_id=owner, room_id=room_id, open=True, now=t0)
                assert opened['open'] and opened['open_expires_at']
            async with db.transaction() as session:
                items = await RoomApplicationService(session).list_open(account_id=stranger, now=t0)
                assert items == [{
                    'room_id': room_id, 'title': 'Ночной стол', 'host_name': 'Хозяин', 'seated': 1,
                    'waiting': 0, 'needs_from': 4, 'capacity': 12, 'status': 'gathering', 'world': 'manor_lake', 'world_age': 12,
                    'joined': False}]
                assert str(owner) not in str(items) and 'account' not in str(items)
                assert (await RoomApplicationService(session).list_open(
                    account_id=stranger, now=t0 + OPEN_ROOM_IDLE - timedelta(seconds=1)))
                assert await RoomApplicationService(session).list_open(
                    account_id=stranger, now=t0 + OPEN_ROOM_IDLE + timedelta(seconds=1)) == []
            # Table activity keeps a listed room listed; it never revives an expired one.
            async with db.transaction() as session:
                await session.execute(update(Room).where(Room.id == room_id).values(
                    open_activity_at=datetime.now(timezone.utc) - timedelta(minutes=25)))
            lobby = await lobby_of(db, room_id, owner)
            await mafia(db, 'room_ready', room_id=room_id, account_id=owner, ready=True,
                        expected_revision=lobby['revision'])
            async with db.transaction() as session:
                room = await session.get(Room, room_id)
                assert room.open_activity_at > datetime.now(timezone.utc) - timedelta(minutes=1)
                room.open_activity_at = datetime.now(timezone.utc) - timedelta(minutes=45)
            lobby = await lobby_of(db, room_id, owner)
            await mafia(db, 'room_ready', room_id=room_id, account_id=owner, ready=False,
                        expected_revision=lobby['revision'])
            async with db.transaction() as session:
                assert await RoomApplicationService(session).list_open(account_id=stranger) == []
                assert (await session.get(Room, room_id)).open_activity_at < datetime.now(timezone.utc) - timedelta(minutes=40)
            with pytest.raises(LookupError, match='не открыта'):
                await join_open(db, room_id, stranger)
            # Closing by the owner.
            async with db.transaction() as session:
                closed = await RoomApplicationService(session).set_open(
                    account_id=owner, room_id=room_id, open=False)
                assert closed['open'] is False and closed['open_expires_at'] is None
    asyncio.run(run())


def test_join_open_seat_wait_rematch_remove_and_invite_return(pg_url, monkeypatch):
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)

    async def run():
        async with isolated_database(pg_url) as (db, _):
            owner, p2, p3, p4, late, other = await make_accounts(db, 6)
            room_id = await make_room(db, owner)
            for account in (p2, p3, p4):
                result = await join_open(db, room_id, account)
                assert result['joined'] and result['seat'] == 'seated' and result['room']['role'] == 'member'
            again = await join_open(db, room_id, p2)  # new command, already a member: no new entry
            assert again['joined'] is False and again['seat'] == 'seated'
            assert len(again['lobby']['players']) == 4
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(RoomMembership).where(
                    RoomMembership.room_id == room_id)) == 4
            await ready_all(db, room_id, [owner, p2, p3, p4])
            lobby = await lobby_of(db, room_id, owner)
            assert lobby['can_start']
            started = await mafia(db, 'room_start', room_id=room_id, account_id=owner,
                                  expected_revision=lobby['revision'])
            assert started['status'] == 'night'

            # During the game: waiting for the next one, listed as «идёт партия».
            waiting = await join_open(db, room_id, late, 'Опоздавший')
            assert waiting['seat'] == 'waiting' and waiting['lobby']['is_waiting']
            assert not waiting['lobby']['joined']
            with pytest.raises(ValueError, match='играешь'):
                await mafia(db, 'room_wait', room_id=room_id, account_id=p2, name='x')
            async with db.transaction() as session:
                item = (await RoomApplicationService(session).list_open(account_id=other))[0]
                assert item['status'] == 'playing' and item['seated'] == 4 and item['waiting'] == 1
            with pytest.raises(PermissionError):  # a waiting player is not at the table
                async with db.transaction() as session:
                    await MafiaApplicationService(session).room_role(room_id=room_id, account_id=late)

            # Play it out: mafia (owner) kills p2; citizens vote the mafia out.
            night = await mafia(db, 'room_action', room_id=room_id, account_id=owner, target_seat='p2',
                                expected_revision=started['phase_revision'])
            assert night['lobby']['status'] == 'night'  # everyone has acted, the night still runs to its deadline
            assert (await end_phase(db, room_id))['status'] == 'day'
            day = await lobby_of(db, room_id, owner)
            voting = await mafia(db, 'room_advance', room_id=room_id, account_id=owner,
                                 expected_revision=day['revision'])
            phase = voting['lobby']['phase_revision']
            await mafia(db, 'room_vote', room_id=room_id, account_id=p3, target_seat='p1', expected_revision=phase)
            await mafia(db, 'room_vote', room_id=room_id, account_id=p4, target_seat='p1', expected_revision=phase)
            last = await mafia(db, 'room_vote', room_id=room_id, account_id=owner, target_seat='p3',
                               expected_revision=phase)
            assert last['lobby']['status'] == 'finished' and last['lobby']['winner'] == 'citizens'

            restarted = await mafia(db, 'room_restart', room_id=room_id, account_id=owner,
                                    expected_revision=last['lobby']['revision'])
            names = [p['name'] for p in restarted['lobby']['players']]
            assert names == ['Хозяин', 'Гость', 'Гость', 'Гость', 'Опоздавший'] and restarted['lobby']['waiting'] == []
            assert len({p['portrait'] for p in restarted['lobby']['players']}) == 5

            # Owner removes a seated stranger from the lobby: out of the room, back only by invitation.
            lobby = await lobby_of(db, room_id, owner)
            removed = await mafia(db, 'room_remove_player', room_id=room_id, account_id=owner,
                                  target='p5', expected_revision=lobby['revision'])
            assert [p['name'] for p in removed['players']] == ['Хозяин', 'Гость', 'Гость', 'Гость']
            async with db.transaction() as session:
                assert (await session.get(RoomMembership, (room_id, late))).status == 'removed'
                with pytest.raises(LookupError):
                    await RoomApplicationService(session).get_mine(account_id=late, room_id=room_id)
            with pytest.raises(PermissionError, match='приглашению'):
                await join_open(db, room_id, late)
            with pytest.raises(PermissionError):  # only the owner removes
                await mafia(db, 'room_remove_player', room_id=room_id, account_id=p2, target='p3',
                            expected_revision=removed['revision'])
            async with db.transaction() as session:
                invite = await RoomApplicationService(session).create_invite(
                    account_id=owner, room_id=room_id, expires_in_seconds=3600, max_uses=5)
                back = await RoomApplicationService(session).join_by_invite(
                    account_id=late, invite_code=invite['invite_code'])
                assert back['joined'] is True and back['role'] == 'member'
            seated = await join_open(db, room_id, late)  # member again: sits at the unstarted table
            assert seated['seat'] == 'seated' and seated['joined'] is False
            # The host cannot be removed; a stranger can stand up from the lobby.
            lobby = await lobby_of(db, room_id, owner)
            with pytest.raises(ValueError, match='Себя'):
                await mafia(db, 'room_remove_player', room_id=room_id, account_id=owner,
                            target='p1', expected_revision=lobby['revision'])
            stood = await mafia(db, 'room_unseat', room_id=room_id, account_id=late)
            assert len(stood['players']) == 4
    asyncio.run(run())


def test_removed_while_waiting_and_wait_cancel(pg_url, monkeypatch):
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)

    async def run():
        async with isolated_database(pg_url) as (db, _):
            owner, p2, p3, p4, w1, w2 = await make_accounts(db, 6)
            room_id = await make_room(db, owner)
            for account in (p2, p3, p4):
                await join_open(db, room_id, account)
            lobby = await ready_all(db, room_id, [owner, p2, p3, p4])
            started = await mafia(db, 'room_start', room_id=room_id, account_id=owner,
                                  expected_revision=lobby['revision'])
            await join_open(db, room_id, w1, 'W1')
            await join_open(db, room_id, w2, 'W2')
            lobby = await lobby_of(db, room_id, owner)
            assert [w['ref'] for w in lobby['waiting']] == ['w1', 'w2']
            lobby = (await mafia(db, 'room_remove_player', room_id=room_id, account_id=owner, target='w1',
                                 expected_revision=lobby['revision']))
            assert [w['name'] for w in lobby['waiting']] == ['W2']
            canceled = await mafia(db, 'room_unseat', room_id=room_id, account_id=w2)
            assert canceled['waiting'] == [] and canceled['is_waiting'] is False
            with pytest.raises(ValueError, match='Во время партии'):
                await mafia(db, 'room_remove_player', room_id=room_id, account_id=owner, target='p2',
                            expected_revision=canceled['revision'])
    asyncio.run(run())


def test_race_for_the_last_seat_has_exactly_one_winner(pg_url):
    async def run():
        async with isolated_database(pg_url) as (db, _):
            accounts = await make_accounts(db, 13)
            owner, seated, racers = accounts[0], accounts[1:11], accounts[11:]
            room_id = await make_room(db, owner)
            for account in seated:
                await join_open(db, room_id, account)
            assert len((await lobby_of(db, room_id, owner))['players']) == 11

            async def attempt(account):
                try:
                    return await join_open(db, room_id, account)
                except TableFull as error:
                    return error

            results = await asyncio.gather(*(attempt(a) for a in racers))
            winners = [r for r in results if isinstance(r, dict)]
            losers = [r for r in results if isinstance(r, TableFull)]
            assert len(winners) == 1 and len(losers) == 1 and winners[0]['seat'] == 'seated'
            lobby = await lobby_of(db, room_id, owner)
            assert len(lobby['players']) == 12 and len({p['portrait'] for p in lobby['players']}) == 12
            async with db.transaction() as session:
                loser = racers[results.index(losers[0])]
                assert await session.get(RoomMembership, (room_id, loser)) is None  # refused: no membership
                item = (await RoomApplicationService(session).list_open(account_id=loser))[0]
                assert item['status'] == 'full' and item['seated'] == 12
            with pytest.raises(TableFull):
                await join_open(db, room_id, loser)
    asyncio.run(run())


def test_race_for_the_last_waiting_place(pg_url, monkeypatch):
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)

    async def run():
        async with isolated_database(pg_url) as (db, _):
            accounts = await make_accounts(db, 14)
            owner = accounts[0]
            room_id = await make_room(db, owner)
            for account in accounts[1:4]:
                await join_open(db, room_id, account)
            lobby = await ready_all(db, room_id, accounts[:4])
            await mafia(db, 'room_start', room_id=room_id, account_id=owner, expected_revision=lobby['revision'])
            for account in accounts[4:11]:  # 4 players + 7 waiting = 11 of 12 places
                assert (await join_open(db, room_id, account))['seat'] == 'waiting'

            async def attempt(account):
                try:
                    return await join_open(db, room_id, account)
                except TableFull as error:
                    return error

            results = await asyncio.gather(*(attempt(a) for a in accounts[11:13]))
            assert sorted(type(r).__name__ for r in results) == ['TableFull', 'dict']
            lobby = await lobby_of(db, room_id, owner)
            assert len(lobby['players']) + len(lobby['waiting']) == 12
            async with db.transaction() as session:
                assert (await RoomApplicationService(session).list_open(account_id=accounts[13]))[0]['status'] == 'full'
    asyncio.run(run())


def test_membership_changes_are_rate_limited_per_account(pg_url):
    async def run():
        async with isolated_database(pg_url) as (db, _):
            first, second = await make_accounts(db, 2)
            t0 = datetime.now(timezone.utc)
            async with db.transaction() as session:
                for _ in range(room_limits.MEMBERSHIP_LIMIT):
                    await room_limits.charge_membership(session, first, t0)
            with pytest.raises(RoomRateLimited) as caught:
                async with db.transaction() as session:
                    await room_limits.charge_membership(session, first, t0 + timedelta(minutes=1))
            assert 1 <= caught.value.retry_after <= 600
            async with db.transaction() as session:  # other accounts are not affected
                await room_limits.charge_membership(session, second, t0)
                await room_limits.charge_membership(session, first, t0 + room_limits.MEMBERSHIP_WINDOW
                                                    + timedelta(seconds=1))

            # Through the commands: open entries of one account are counted, the 21st is refused.
            owner = (await make_accounts(db, 1))[0]
            room_id = await make_room(db, owner)
            joiner = (await make_accounts(db, 1))[0]
            await join_open(db, room_id, joiner)
            async with db.transaction() as session:
                for _ in range(room_limits.MEMBERSHIP_LIMIT - 1):
                    await room_limits.charge_membership(session, joiner)
            lobby = await lobby_of(db, room_id, owner)
            await mafia(db, 'room_remove_player', room_id=room_id, account_id=owner, target='p2',
                        expected_revision=lobby['revision'])
            async with db.transaction() as session:
                invite = await RoomApplicationService(session).create_invite(
                    account_id=owner, room_id=room_id, expires_in_seconds=3600, max_uses=5)
            with pytest.raises(RoomRateLimited):
                async with db.transaction() as session:
                    await RoomApplicationService(session).join_by_invite(
                        account_id=joiner, invite_code=invite['invite_code'])
    asyncio.run(run())


async def attempt_code(db, account, code, now=None, client=None):
    """Answer from inside the transaction, like the HTTP adapter, so a failure stays counted."""
    async with db.transaction() as session:
        try:
            return await RoomApplicationService(session).join_by_short_code(
                account_id=account, code=code, now=now, client=client)
        except (InviteRejected, RoomRateLimited) as error:
            return error


def test_short_code_join_reasons_hash_only_and_shared_uses(pg_url):
    async def run():
        async with isolated_database(pg_url) as (db, _):
            owner, a, b, c, d = await make_accounts(db, 5)
            room_id = await make_room(db, owner, 'Дело «Север»', open_room=False)
            async with db.transaction() as session:
                invite = await RoomApplicationService(session).create_invite(
                    account_id=owner, room_id=room_id, expires_in_seconds=3600, max_uses=2)
            code = invite['short_code']
            assert re.fullmatch(r'[A-HJKMNP-TV-Z2-9]{4}-[A-HJKMNP-TV-Z2-9]{4}', code)
            assert invite['invite_code'] and len(invite['invite_code']) == 43
            async with db.transaction() as session:  # only hashes are stored
                row = await session.scalar(select(RoomInvite).where(RoomInvite.id == invite['id']))
                assert row.short_hash == room_limits.short_code_hash(code.replace('-', ''))
                assert code.replace('-', '') not in str(row.__dict__) and invite['invite_code'] not in str(row.__dict__)
                listed = await RoomApplicationService(session).list_invites(account_id=owner, room_id=room_id)
                assert code not in str(listed) and 'short' not in str(listed)

            typed = code.lower().replace('-', ' ')
            joined = await attempt_code(db, a, typed)
            assert isinstance(joined, dict) and joined['joined'] is True and joined['title'] == 'Дело «Север»'
            replay = await attempt_code(db, a, code)  # member: idempotent, not a failure
            assert replay['joined'] is False
            via_link = None
            async with db.transaction() as session:  # the long token spends the same uses
                via_link = await RoomApplicationService(session).join_by_invite(
                    account_id=b, invite_code=invite['invite_code'])
                assert via_link['joined']
            exhausted = await attempt_code(db, c, code)
            assert isinstance(exhausted, InviteRejected) and exhausted.reason == 'exhausted'
            assert exhausted.room_title == 'Дело «Север»' and 'Дело «Север»' in str(exhausted)

            async with db.transaction() as session:
                second = await RoomApplicationService(session).create_invite(
                    account_id=owner, room_id=room_id, expires_in_seconds=3600, max_uses=3)
                await RoomApplicationService(session).revoke_invite(
                    account_id=owner, room_id=room_id, invite_id=second['id'])
                third = await RoomApplicationService(session).create_invite(
                    account_id=owner, room_id=room_id, expires_in_seconds=600, max_uses=3)
            revoked = await attempt_code(db, c, second['short_code'])
            assert revoked.reason == 'revoked' and revoked.room_title == 'Дело «Север»'
            expired = await attempt_code(db, c, third['short_code'], now=datetime.now(timezone.utc) + timedelta(minutes=11))
            assert expired.reason == 'expired'
            unknown = await attempt_code(db, c, 'ZZZZ-ZZZZ')
            assert unknown.reason == 'unknown' and unknown.room_title is None
            malformed = await attempt_code(db, c, 'hello')
            assert malformed.reason == 'unknown'
            async with db.transaction() as session:  # failures were persisted: 5 so far for c
                assert await session.scalar(select(func.count()).select_from(RoomJoinAttempt).where(
                    RoomJoinAttempt.account_id == c, RoomJoinAttempt.kind == 'code_fail')) == 5
            # The long token keeps its single generic refusal.
            with pytest.raises(LookupError, match='недействительно'):
                async with db.transaction() as session:
                    await RoomApplicationService(session).join_by_invite(
                        account_id=d, invite_code=invite['invite_code'])
    asyncio.run(run())


def test_short_code_guessing_is_limited_per_account_and_per_client_address(pg_url, monkeypatch):
    async def run():
        async with isolated_database(pg_url) as (db, _):
            owner, guesser, other, *crowd = await make_accounts(db, 10)
            room_id = await make_room(db, owner, open_room=False)
            async with db.transaction() as session:
                invite = await RoomApplicationService(session).create_invite(
                    account_id=owner, room_id=room_id, expires_in_seconds=6 * 3600, max_uses=50)
            t0 = datetime.now(timezone.utc)
            for _ in range(room_limits.CODE_FAIL_ACCOUNT_LIMIT):
                assert (await attempt_code(db, guesser, 'AAAA-AAAA', now=t0)).reason == 'unknown'
            blocked = await attempt_code(db, guesser, invite['short_code'], now=t0 + timedelta(minutes=1))
            assert isinstance(blocked, RoomRateLimited) and blocked.retry_after >= 1  # even the right code
            ok = await attempt_code(db, other, invite['short_code'], now=t0 + timedelta(minutes=1))
            assert ok['joined'] is True  # other accounts are unaffected
            after = await attempt_code(db, guesser, invite['short_code'],
                                       now=t0 + room_limits.CODE_FAIL_ACCOUNT_WINDOW + timedelta(seconds=1))
            assert after['joined'] is True

            # One address farming accounts is stopped; everybody else (other addresses) keeps entering codes.
            monkeypatch.setattr(room_limits, 'CODE_FAIL_CLIENT_LIMIT', 4)
            t1 = t0 + timedelta(hours=3)
            for account in crowd[:4]:
                assert (await attempt_code(db, account, 'BBBB-BBBB', now=t1, client='addr-a')).reason == 'unknown'
            blocked = await attempt_code(db, crowd[5], 'BBBB-BBBB', now=t1 + timedelta(seconds=5), client='addr-a')
            assert isinstance(blocked, RoomRateLimited) and 'адреса' in str(blocked)
            right = await attempt_code(db, crowd[5], invite['short_code'], now=t1 + timedelta(seconds=6), client='addr-a')
            assert isinstance(right, RoomRateLimited)  # even the right code from the blocked address
            elsewhere = await attempt_code(db, crowd[6], invite['short_code'], now=t1 + timedelta(seconds=7), client='addr-b')
            assert elsewhere['joined'] is True  # no global lock-out: another address is unaffected
            later = await attempt_code(db, crowd[5], 'BBBB-BBBB', client='addr-a',
                                       now=t1 + room_limits.CODE_FAIL_CLIENT_WINDOW + timedelta(seconds=1))
            assert later.reason == 'unknown'
            async with db.transaction() as session:  # only a hash of the address is stored, and only for failures
                stored = (await session.scalars(select(RoomJoinAttempt.client_hash).where(
                    RoomJoinAttempt.kind == 'code_fail'))).all()
                assert set(stored) == {None, 'addr-a'}
    asyncio.run(run())


def test_early_close_goes_through_the_deadline_path_without_duplicates(pg_url, monkeypatch):
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)
    from application.game_deadlines import GameDeadlineProcessor
    from storage.models import AccountIdentity, User

    async def run():
        async with isolated_database(pg_url) as (db, _):
            owner, p2, p3, p4 = await make_accounts(db, 4)
            now = datetime.now(timezone.utc)
            async with db.transaction() as session:
                for index, account in enumerate((owner, p2, p3, p4)):
                    session.add(User(id=9500 + index, account_id=account, display_name=f'U{index}'))
                await session.flush()
                for index, account in enumerate((owner, p2, p3, p4)):
                    session.add(AccountIdentity(account_id=account, provider='telegram',
                                                provider_subject=str(9500 + index), verified_at=now, linked_at=now))
            room_id = await make_room(db, owner)
            for account in (p2, p3, p4):
                await join_open(db, room_id, account)
            lobby = await ready_all(db, room_id, [owner, p2, p3, p4])
            started = await mafia(db, 'room_start', room_id=room_id, account_id=owner,
                                  expected_revision=lobby['revision'])
            async with db.transaction() as session:
                before = len((await session.scalars(select(NotificationOutbox).where(
                    NotificationOutbox.kind == 'mafia.room_phase'))).all())
            night = await mafia(db, 'room_action', room_id=room_id, account_id=owner, target_seat='p2',
                                expected_revision=started['phase_revision'])
            # Everyone who acts has acted, and still the night does not close: it ends by its deadline, so the
            # moment it ends tells nobody that the detective or the doctor is dead.
            assert night['lobby']['status'] == 'night' and night['lobby']['can_advance'] is False
            async with db.transaction() as session:
                assert len((await session.scalars(select(NotificationOutbox).where(
                    NotificationOutbox.kind == 'mafia.room_phase'))).all()) == before
                assert (await session.scalars(select(GameEvent.kind).where(
                    GameEvent.kind == 'early_advanced'))).all() == []
            with pytest.raises(ValueError, match='таймеру'):  # the host cannot end it by hand either
                await mafia(db, 'room_advance', room_id=room_id, account_id=owner,
                            expected_revision=night['lobby']['revision'])
            late = datetime.fromtimestamp(started['ends_at'], tz=timezone.utc) + timedelta(seconds=1)
            assert (await GameDeadlineProcessor(db).run_once(now=late))['mafia'] == 1
            async with db.transaction() as session:
                rows = (await session.scalars(select(NotificationOutbox).where(
                    NotificationOutbox.kind == 'mafia.room_phase'))).all()
                day = [r for r in rows if r.payload['status'] == 'day']
                assert sorted(r.user_id for r in day) == [9500, 9501, 9502, 9503] and len(rows) == before + 4
            assert (await GameDeadlineProcessor(db).run_once(now=late))['mafia'] == 0  # nothing left to do for it
            lobby_now = await lobby_of(db, room_id, owner)
            assert lobby_now['status'] == 'day' and lobby_now['history'][-1]['eliminated'] == 'p2'

            # The voting, on the other hand, closes as soon as every living player has voted - once.
            voting = (await mafia(db, 'room_advance', room_id=room_id, account_id=owner,
                                  expected_revision=lobby_now['revision']))['lobby']
            for voter in (p3, p4):
                await mafia(db, 'room_vote', room_id=room_id, account_id=voter, target_seat='p1',
                            expected_revision=voting['phase_revision'])
            assert (await lobby_of(db, room_id, owner))['status'] == 'voting'
            closed = await mafia(db, 'room_vote', room_id=room_id, account_id=owner, target_seat='p3',
                                 expected_revision=voting['phase_revision'])
            assert closed['lobby']['status'] == 'finished' and closed['lobby']['winner'] == 'citizens'
            async with db.transaction() as session:
                assert (await session.scalars(select(GameEvent.kind).where(
                    GameEvent.kind == 'early_advanced'))).all() == ['early_advanced']
    asyncio.run(run())


def test_telegram_group_table_status_comes_from_stored_data(pg_url):
    from storage.mini_app import MiniAppStore
    from storage.repositories import OperationalRepository

    async def run():
        async with isolated_database(pg_url) as (db, _):
            chats = (-870000001001, -870000001002, -870000001003)
            async with db.transaction() as session:
                repository = OperationalRepository(session)
                for chat in chats:
                    await repository.ensure_chat({'id': chat, 'type': 'supergroup', 'title': f'Группа {chat}'})
                for user_id in range(8601, 8606):
                    await repository.ensure_user({'id': user_id, 'display_name': f'Игрок {user_id}'})
                    for chat in chats[:2]:
                        await repository.ensure_member({'chat_id': chat, 'user_id': user_id})
            async with db.transaction() as session:
                service = MafiaApplicationService(session)
                for user_id in range(8601, 8606):
                    lobby = (await service.join(chat_id=chats[0], user_id=user_id, name=f'И{user_id}'))['lobby']
                await service.join(chat_id=chats[1], user_id=8601, name='Один')
                # 4 of 5 ready: a group table keeps «everybody ready» (no queue on its screen); rooms do not.
                for user_id in range(8601, 8605):
                    lobby = await service.ready(chat_id=chats[0], user_id=user_id, ready=True,
                                                expected_revision=lobby['revision'])
                assert not lobby['can_start'] and lobby['ready_count'] == 4 and lobby['start_requires_all_ready']
                with pytest.raises(ValueError, match='готовы все'):
                    await service.start(chat_id=chats[0], user_id=8601, expected_revision=lobby['revision'])
                lobby = await service.ready(chat_id=chats[0], user_id=8605, ready=True,
                                            expected_revision=lobby['revision'])
                assert lobby['can_start'] and lobby['ready_count'] == 5
            async with db.transaction() as session:
                tables = await MiniAppStore.mafia_tables(session, list(chats), 8601)
                assert tables[chats[0]] == {'status': 'gathering', 'seated': 5, 'joined': True}
                assert tables[chats[1]] == {'status': 'gathering', 'seated': 1, 'joined': True}
                assert tables[chats[2]] == {'status': 'none', 'seated': 0, 'joined': False}
                assert (await MiniAppStore.mafia_tables(session, [chats[0]], 8999))[chats[0]]['joined'] is False
            async with db.transaction() as session:
                started = await MafiaApplicationService(session).start(
                    chat_id=chats[0], user_id=8601, expected_revision=lobby['revision'])
                assert started['status'] == 'night' and len(started['players']) == 5
                assert not started.get('waiting')
            async with db.transaction() as session:
                tables = await MiniAppStore.mafia_tables(session, list(chats), 8605)
                assert tables[chats[0]] == {'status': 'playing', 'seated': 5, 'joined': True}
    asyncio.run(run())


async def leave_room(db, room_id, account, version=None):
    async with db.transaction() as session:
        if version is None:
            version = (await RoomApplicationService(session).get_mine(
                account_id=account, room_id=room_id))['membership_version']
        return await RoomApplicationService(session).leave(
            account_id=account, room_id=room_id, membership_version=version)


def test_leaving_the_room_at_the_lobby_in_the_queue_and_in_a_running_game(pg_url, monkeypatch):
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)
    from storage.models import AccountIdentity, User

    async def run():
        async with isolated_database(pg_url) as (db, _):
            owner, p2, p3, p4, p5, late, seated = await make_accounts(db, 7)
            now = datetime.now(timezone.utc)
            async with db.transaction() as session:
                for index, account in enumerate((owner, p2, p3, p4, p5)):
                    session.add(User(id=9600 + index, account_id=account, display_name=f'U{index}'))
                await session.flush()
                for index, account in enumerate((owner, p2, p3, p4, p5)):
                    session.add(AccountIdentity(account_id=account, provider='telegram',
                                                provider_subject=str(9600 + index), verified_at=now, linked_at=now))
            room_id = await make_room(db, owner)
            for account in (p2, p3, p4, p5, seated):
                await join_open(db, room_id, account)

            # Unstarted table: one command stands up and drops the membership; the host cannot leave.
            async with db.transaction() as session:
                seated_version = (await RoomApplicationService(session).get_mine(
                    account_id=seated, room_id=room_id))['membership_version']
            assert await leave_room(db, room_id, seated) == {'left': True, 'table': 'unseated'}
            assert await leave_room(db, room_id, seated, seated_version) == {'left': False}  # replay
            with pytest.raises(PermissionError, match='Владелец'):
                await leave_room(db, room_id, owner)
            lobby = await ready_all(db, room_id, [owner, p2, p3, p4, p5])
            assert len(lobby['players']) == 5
            started = await mafia(db, 'room_start', room_id=room_id, account_id=owner,
                                  expected_revision=lobby['revision'])
            await join_open(db, room_id, late, 'Опоздавший')
            # Queue place of the running game: leaving gives it up.
            assert await leave_room(db, room_id, late) == {'left': True, 'table': 'waiting'}
            assert (await lobby_of(db, room_id, owner))['waiting'] == []

            # Night: the mafia has chosen, the detective (p5) was the last missing actor and vanishes -
            # the night still runs to its deadline (a quick end would show that nobody is left to act).
            await mafia(db, 'room_action', room_id=room_id, account_id=owner, target_seat='p2',
                        expected_revision=started['phase_revision'])
            async with db.transaction() as session:
                before = len((await session.scalars(select(NotificationOutbox).where(
                    NotificationOutbox.kind == 'mafia.room_phase'))).all())
            async with db.transaction() as session:
                p5_version = (await RoomApplicationService(session).get_mine(
                    account_id=p5, room_id=room_id))['membership_version']
            assert await leave_room(db, room_id, p5) == {'left': True, 'table': 'vanished'}
            still_night = await lobby_of(db, room_id, owner)
            assert still_night['status'] == 'night' and still_night['players'][4]['alive'] is False
            assert still_night['history'][-1] == {'type': 'vanished', 'round': 1, 'seat': 'p5',
                                                  'name': still_night['players'][4]['name']}
            async with db.transaction() as session:
                assert len((await session.scalars(select(NotificationOutbox).where(
                    NotificationOutbox.kind == 'mafia.room_phase'))).all()) == before  # no early close
            assert (await end_phase(db, room_id))['status'] == 'day'
            day = await lobby_of(db, room_id, owner)
            assert day['status'] == 'day' and day['players'][4]['alive'] is False
            assert day['history'][-2] == {'type': 'vanished', 'round': 1, 'seat': 'p5',
                                          'name': day['players'][4]['name']}
            assert day['history'][-1]['eliminated'] == 'p2' and 'role' not in str(day['history'][-2])
            async with db.transaction() as session:
                assert (await session.get(RoomMembership, (room_id, p5))).status == 'inactive'
                rows = (await session.scalars(select(NotificationOutbox).where(
                    NotificationOutbox.kind == 'mafia.room_phase'))).all()
                fresh = [r for r in rows if r.payload['status'] == 'day']
                # one nudge per Telegram-linked member who stayed; the leaver (9604) gets nothing
                assert sorted(r.user_id for r in fresh) == [9600, 9601, 9602, 9603] and len(rows) == before + 4
                kinds = (await session.scalars(select(GameEvent.kind).where(
                    GameEvent.kind.in_(['player_vanished', 'early_advanced', 'deadline_advanced'])))).all()
                assert sorted(kinds) == ['deadline_advanced', 'player_vanished']
            with pytest.raises(LookupError):  # a vanished hero is out of the table
                await lobby_of(db, room_id, p5)
            assert await leave_room(db, room_id, p5, p5_version) == {'left': False}

            # Day: p4 vanishes, town 1 vs mafia 1 - the mafia wins on parity. A finished table: p3 just leaves.
            assert await leave_room(db, room_id, p4) == {'left': True, 'table': 'vanished'}
            final = await lobby_of(db, room_id, owner)
            assert final['status'] == 'finished' and final['winner'] == 'mafia'
            assert final['players'][0]['role'] == 'mafia' and final['history'][-1]['type'] == 'vanished'
            assert await leave_room(db, room_id, p3) == {'left': True}
            async with db.transaction() as session:
                finished = [r for r in (await session.scalars(select(NotificationOutbox).where(
                    NotificationOutbox.kind == 'mafia.room_phase'))).all() if r.payload['status'] == 'finished']
                assert {r.user_id for r in finished} == {9600, 9601, 9602}  # nobody who left is nudged
    asyncio.run(run())


def test_remove_revokes_every_standing_invitation_and_the_removed_gets_invite_revoked(pg_url):
    async def run():
        async with isolated_database(pg_url) as (db, _):
            owner, friend, outsider = await make_accounts(db, 3)
            room_id = await make_room(db, owner)
            async with db.transaction() as session:
                shared = await RoomApplicationService(session).create_invite(
                    account_id=owner, room_id=room_id, expires_in_seconds=3600, max_uses=10)
                other = await RoomApplicationService(session).create_invite(
                    account_id=owner, room_id=room_id, expires_in_seconds=3600, max_uses=10)
            assert (await attempt_code(db, friend, shared['short_code']))['joined'] is True
            await join_open(db, room_id, friend, 'Друг')  # sits at the table, then the owner removes him
            lobby = await lobby_of(db, room_id, owner)
            await mafia(db, 'room_remove_player', room_id=room_id, account_id=owner, target='p2',
                        expected_revision=lobby['revision'])
            async with db.transaction() as session:
                rows = (await session.scalars(select(RoomInvite).where(RoomInvite.room_id == room_id))).all()
                assert len(rows) == 2 and all(row.revoked_at is not None for row in rows)
                listed = await RoomApplicationService(session).list_invites(account_id=owner, room_id=room_id)
                assert all(item['revoked'] for item in listed)
            for code in (shared['short_code'], other['short_code']):
                refused = await attempt_code(db, friend, code)
                assert isinstance(refused, InviteRejected) and refused.reason == 'revoked'
            with pytest.raises(LookupError):  # the link is dead too (one generic refusal)
                async with db.transaction() as session:
                    await RoomApplicationService(session).join_by_invite(
                        account_id=friend, invite_code=other['invite_code'])
            stranger = await attempt_code(db, outsider, other['short_code'])
            assert isinstance(stranger, InviteRejected) and stranger.reason == 'revoked'  # nobody uses the old ones
            async with db.transaction() as session:  # the host hands out a fresh one: that works
                fresh = await RoomApplicationService(session).create_invite(
                    account_id=owner, room_id=room_id, expires_in_seconds=3600, max_uses=5)
            assert (await attempt_code(db, friend, fresh['short_code']))['joined'] is True
    asyncio.run(run())


def test_short_code_hash_is_keyed_and_survives_restarts_and_legacy_codes_still_join(pg_url, monkeypatch):
    monkeypatch.delenv('MQB_ROOM_CODE_SECRET', raising=False)
    monkeypatch.setattr(room_limits, '_fallback_secret', '123456789:' + 'A' * 35)
    keyed = room_limits.short_code_hash('K7Q4MD2X')
    legacy = room_limits._legacy_hash('K7Q4MD2X')
    assert keyed != legacy and len(keyed) == 64
    assert room_limits.short_code_hashes('K7Q4MD2X') == [keyed, legacy]
    assert room_limits.short_code_hash('K7Q4MD2X') == keyed  # stable: same secret, same hash (a restart)
    monkeypatch.setenv('MQB_ROOM_CODE_SECRET', 'x' * 40)
    assert room_limits.short_code_hash('K7Q4MD2X') not in {keyed, legacy}  # the explicit secret wins
    monkeypatch.setenv('MQB_ROOM_CODE_SECRET', 'short')  # too short to trust: ignored
    assert room_limits.short_code_hash('K7Q4MD2X') == keyed
    monkeypatch.delenv('MQB_ROOM_CODE_SECRET')
    monkeypatch.setattr(room_limits, '_fallback_secret', '')
    assert room_limits.short_code_hashes('K7Q4MD2X') == [legacy]  # offline / tests: no secret at all

    async def run():
        monkeypatch.setattr(room_limits, '_fallback_secret', '123456789:' + 'A' * 35)
        async with isolated_database(pg_url) as (db, _):
            owner, new_user, old_user = await make_accounts(db, 3)
            room_id = await make_room(db, owner, open_room=False)
            async with db.transaction() as session:
                invite = await RoomApplicationService(session).create_invite(
                    account_id=owner, room_id=room_id, expires_in_seconds=3600, max_uses=5)
                old = await RoomApplicationService(session).create_invite(
                    account_id=owner, room_id=room_id, expires_in_seconds=3600, max_uses=5)
                row = await session.scalar(select(RoomInvite).where(RoomInvite.id == old['id']))
                normalized = room_limits.normalize_short_code(old['short_code'])
                assert row.short_hash == room_limits.short_code_hash(normalized) != room_limits._legacy_hash(normalized)
                row.short_hash = room_limits._legacy_hash(normalized)  # as issued before the secret existed
            assert (await attempt_code(db, new_user, invite['short_code']))['joined'] is True
            assert (await attempt_code(db, old_user, old['short_code']))['joined'] is True  # legacy hash still accepted
    asyncio.run(run())


def test_parallel_code_entries_of_one_account_never_deadlock_with_leave_and_open_join(pg_url):
    async def run():
        async with isolated_database(pg_url) as (db, _):
            owner, walker = await make_accounts(db, 2)
            room_id = await make_room(db, owner)
            async with db.transaction() as session:
                invite = await RoomApplicationService(session).create_invite(
                    account_id=owner, room_id=room_id, expires_in_seconds=3600, max_uses=100)
            for _ in range(6):
                results = await asyncio.gather(
                    attempt_code(db, walker, invite['short_code']),
                    attempt_code(db, walker, 'ZZZZ-ZZZZ'),
                    attempt_code(db, walker, invite['short_code']),
                    leave_room(db, room_id, walker),
                    join_open(db, room_id, walker, 'Ходок'),
                    return_exceptions=True)
                for result in results:
                    if isinstance(result, BaseException):
                        # every refusal is a business answer; a database deadlock error would be the bug
                        assert isinstance(result, (RoomRateLimited, LookupError, RuntimeError, ValueError,
                                                   PermissionError)), repr(result)
                    if isinstance(result, RoomRateLimited):
                        assert result.retry_after >= 1
    asyncio.run(run())
