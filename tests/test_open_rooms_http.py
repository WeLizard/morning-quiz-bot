"""HTTP contract of open rooms, short codes, early close, discussion rules and account rate limits."""
import asyncio
from uuid import uuid4

from application import room_limits
from tests.test_room_telegram_channel import (ORIGIN, R, environment, guest_client, hdr, new_client, pg_url,  # noqa: F401
                                              post, telegram_client)
from web.mini_app import RequestLimits


async def make_table(owner, title='Открытый стол'):
    room_id = str(uuid4())
    assert (await post(owner, R, {'request_id': room_id, 'title': title})).status_code == 200
    created = await post(owner, f'{R}/{room_id}/mafia/lobby', {}, 'owner-create-1')
    assert created.status_code == 200, created.text
    return room_id, f'{R}/{room_id}/mafia/lobby'


def test_open_room_http_contract(pg_url):
    async def run():
        async with environment(pg_url) as (db, app):
            owner, _ = await guest_client(app)
            guest_a, _ = await guest_client(app)
            guest_b, _ = await guest_client(app)
            tg, _ = await telegram_client(app, db)
            room_id, lobby_path = await make_table(owner)

            # Closed by default; only the owner flips the switch.
            assert (await guest_a.get(f'{R}/open')).json() == {'items': []}
            assert (await post(guest_a, f'{R}/{room_id}/open', {'open': True})).status_code == 404
            assert (await post(owner, f'{R}/{room_id}/open', {'open': 'yes'})).status_code == 400
            switched = await post(owner, f'{R}/{room_id}/open', {'open': True})
            assert switched.status_code == 200 and switched.json()['open'] is True
            assert switched.json()['open_expires_at']
            listed = (await guest_a.get(f'{R}/open')).json()['items']
            assert [(i['room_id'], i['host_name'], i['seated'], i['needs_from'], i['status'], i['joined'])
                    for i in listed] == [(room_id, listed[0]['host_name'], 1, 4, 'gathering', False)]
            assert 'account' not in str(listed) and 'telegram' not in str(listed).lower()

            # A stranger (browser guest) and a Telegram user enter without a code.
            joined = await post(guest_a, f'{R}/{room_id}/join-open', {}, 'a-open-0001')
            assert joined.status_code == 200, joined.text
            body = joined.json()
            assert body['joined'] and body['seat'] == 'seated' and body['lobby']['joined']
            tg_join = await post(tg, f'{R}/{room_id}/join-open', {}, 'tg-open-0001')
            assert tg_join.status_code == 200 and len(tg_join.json()['lobby']['players']) == 3
            replay = await post(guest_a, f'{R}/{room_id}/join-open', {}, 'a-open-0001')
            assert replay.status_code == 200 and replay.json() == body  # idempotent command
            assert (await guest_a.get(f'{R}')).json()['items'][0]['id'] == room_id
            assert (await guest_b.get(f'{R}/{room_id}')).status_code == 404  # not a member yet

            # Portrait: unique at the table, chosen in the lobby.
            lobby = (await guest_a.get(lobby_path)).json()['lobby']
            assert [p['portrait'] for p in lobby['players']] == [1, 2, 3] and lobby['portrait_count'] >= 12
            picked = await post(guest_a, lobby_path + '/portrait',
                                {'portrait': 7, 'expected_revision': lobby['revision']}, 'a-port-0001')
            assert picked.status_code == 200 and picked.json()['lobby']['players'][1]['portrait'] == 7
            taken = await post(tg, lobby_path + '/portrait', {'portrait': 7, 'expected_revision':
                               picked.json()['lobby']['revision']}, 'tg-port-0001')
            assert taken.status_code == 409 and 'занят' in taken.json()['detail']
            assert (await post(tg, lobby_path + '/portrait', {'portrait': 0, 'expected_revision': 1},
                               'tg-port-0002')).status_code == 400

            # Owner removes the Telegram user from the lobby: the open list no longer lets them in.
            lobby = (await owner.get(lobby_path)).json()['lobby']
            assert (await post(guest_a, lobby_path + '/remove', {'target': 'p3', 'expected_revision':
                    lobby['revision']}, 'a-rem-00001')).status_code == 403
            removed = await post(owner, lobby_path + '/remove',
                                 {'target': 'p3', 'expected_revision': lobby['revision']}, 'o-rem-00001')
            assert removed.status_code == 200 and len(removed.json()['lobby']['players']) == 2
            assert (await tg.get(f'{R}/{room_id}')).status_code == 404
            refused = await post(tg, f'{R}/{room_id}/join-open', {}, 'tg-open-0002')
            assert refused.status_code == 403 and refused.json()['code'] == 'removed_from_room'

            # Short code: wrong code first (counted), right one with any case/hyphen; Telegram user returns by it.
            invite = (await post(owner, f'{R}/{room_id}/invites', {'expires_in_seconds': 3600, 'max_uses': 1})).json()
            assert invite['short_code'] == invite['short_code'].upper() and len(invite['short_code']) == 9
            wrong = await post(guest_b, f'{R}/join', {'short_code': 'ZZZZ-ZZZZ'})
            assert wrong.status_code == 404 and wrong.json()['reason'] == 'unknown'
            ok = await post(tg, f'{R}/join', {'short_code': invite['short_code'].lower().replace('-', '')})
            assert ok.status_code == 200 and ok.json()['title'] == 'Открытый стол' and ok.json()['joined']
            exhausted = await post(guest_b, f'{R}/join', {'short_code': invite['short_code']})
            assert exhausted.status_code == 410 and exhausted.json()['reason'] == 'exhausted'
            assert exhausted.json()['room_title'] == 'Открытый стол'
            assert (await post(guest_b, f'{R}/join', {'short_code': 'x', 'invite_code': 'y'})).status_code == 400
            assert (await post(guest_b, f'{R}/join', {})).status_code == 400

            # Wrong guesses are limited per account, even when the failures come as normal answers.
            for _ in range(room_limits.CODE_FAIL_ACCOUNT_LIMIT):
                status = (await post(guest_b, f'{R}/join', {'short_code': 'AAAA-AAAA'})).status_code
            limited = await post(guest_b, f'{R}/join', {'short_code': invite['short_code']})
            assert limited.status_code == 429 and int(limited.headers['retry-after']) >= 1
            assert limited.json()['code'] == 'rate_limited'

            # The rest of the table: start with two unready sitting out, wait for the next game.
            guests = [(await guest_client(app))[0] for _ in range(2)]
            for index, client in enumerate(guests):
                assert (await post(client, f'{R}/{room_id}/join-open', {}, f'g{index}-open-0001')).status_code == 200
            lobby = (await owner.get(lobby_path)).json()['lobby']
            assert len(lobby['players']) == 4 and not lobby['can_start']
            for index, client in enumerate((owner, guest_a, guests[0])):
                current = (await client.get(lobby_path)).json()['lobby']
                assert (await post(client, lobby_path + '/ready', {'ready': True, 'expected_revision':
                        current['revision']}, f'rd-{index}-00001')).status_code == 200
            current = (await owner.get(lobby_path)).json()['lobby']
            assert current['ready_count'] == 3 and not current['can_start']
            current = (await guests[1].get(lobby_path)).json()['lobby']
            assert (await post(guests[1], lobby_path + '/ready', {'ready': True, 'expected_revision':
                    current['revision']}, 'rd-3-000001')).status_code == 200
            late, _ = await guest_client(app)
            current = (await owner.get(lobby_path)).json()['lobby']
            assert current['can_start'] and current['ready_count'] == 4
            late_join = await post(late, f'{R}/{room_id}/join-open', {}, 'late-open-0001')
            assert late_join.status_code == 200 and late_join.json()['seat'] == 'seated'
            current = (await owner.get(lobby_path)).json()['lobby']
            assert len(current['players']) == 5 and current['ready_count'] == 4 and current['can_start']
            started = await post(owner, lobby_path + '/start', {'expected_revision': current['revision']}, 'start-000001')
            assert started.status_code == 200 and started.json()['lobby']['status'] == 'night'
            roster = started.json()['lobby']
            assert len(roster['players']) == 4 and [w['name'] for w in roster['waiting']] == [late_join.json()['lobby']['players'][-1]['name']]
            sat_out = await late.get(lobby_path)
            assert sat_out.json()['lobby']['is_waiting'] is True and (await late.get(f'{R}/{room_id}/mafia/role')).status_code == 404
            cancel = await post(late, lobby_path + '/unseat', {}, 'late-unseat-01')
            assert cancel.status_code == 200 and cancel.json()['lobby']['waiting'] == []
            again = await post(late, lobby_path + '/wait', {}, 'late-wait-0001')
            assert again.status_code == 200 and again.json()['lobby']['is_waiting']
            assert (await guest_a.get(f'{R}/open')).json()['items'][0]['status'] == 'playing'
            for client in (owner, guest_a, guest_b, tg, late, *guests):
                await client.aclose()
    asyncio.run(run())


def test_eliminated_player_reads_but_cannot_post_to_discussion(pg_url, monkeypatch):
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)

    async def run():
        async with environment(pg_url) as (db, app):
            owner, _ = await guest_client(app)
            players = [(await guest_client(app))[0] for _ in range(3)]
            room_id, lobby_path = await make_table(owner)
            invite = (await post(owner, f'{R}/{room_id}/invites', {'expires_in_seconds': 3600, 'max_uses': 5})).json()
            for index, client in enumerate(players):
                assert (await post(client, f'{R}/join', {'short_code': invite['short_code']})).status_code == 200
                assert (await post(client, lobby_path + '/join', {}, f'dj-{index}-000001')).status_code == 200
            for index, client in enumerate([owner, *players]):
                current = (await client.get(lobby_path)).json()['lobby']
                assert (await post(client, lobby_path + '/ready', {'ready': True, 'expected_revision':
                        current['revision']}, f'dr-{index}-000001')).status_code == 200
            current = (await owner.get(lobby_path)).json()['lobby']
            started = (await post(owner, lobby_path + '/start', {'expected_revision': current['revision']}, 'dstart-00001')).json()['lobby']
            # Lobby chat is open to everybody sitting; during the night nobody posts.
            night = await post(owner, f'{R}/{room_id}/mafia/action',
                               {'expected_revision': started['phase_revision'], 'target': 'p2'}, 'dnight-00001')
            assert night.json()['lobby']['status'] == 'night'
            from tests.phase_helpers import end_phase
            assert (await end_phase(db, room_id=room_id))['status'] == 'day'
            dead, alive = players[0], players[1]
            read = (await dead.get(f'{R}/{room_id}/mafia/discussion')).json()
            assert read['enabled'] is True and read['can_post'] is False
            blocked = await post(dead, f'{R}/{room_id}/mafia/discussion', {'message': 'Я выбыл'}, 'dead-talk-0001')
            assert blocked.status_code == 403 and 'читают' in blocked.json()['detail']
            spoke = await post(alive, f'{R}/{room_id}/mafia/discussion', {'message': 'Живой говорит'}, 'live-talk-0001')
            assert spoke.status_code == 200
            seen = (await dead.get(f'{R}/{room_id}/mafia/discussion')).json()
            assert [item['message'] for item in seen['items']] == ['Живой говорит']
            assert (await alive.get(f'{R}/{room_id}/mafia/discussion')).json()['can_post'] is True
            for client in (owner, *players):
                await client.aclose()
    asyncio.run(run())


def test_room_traffic_is_limited_per_account_not_only_per_address(pg_url, monkeypatch):
    monkeypatch.setattr(RequestLimits, 'ROOM_ACCOUNT_LIMIT', 6)

    async def run():
        async with environment(pg_url) as (db, app):
            first, _ = await guest_client(app)
            second, _ = await guest_client(app)  # same address (test transport), other account
            statuses = [(await first.get(R)).status_code for _ in range(8)]
            assert statuses[:6] == [200] * 6 and statuses[6:] == [429, 429]
            assert [(await second.get(R)).status_code for _ in range(6)] == [200] * 6
            assert (await second.get(R)).status_code == 429
            await first.aclose()
            await second.aclose()
    asyncio.run(run())


def test_request_limits_room_buckets():
    now = [0.0]
    limits = RequestLimits(clock=lambda: now[0])
    # Players behind one address: room traffic with a session cookie is not stuck at 120/min.
    assert all(limits.allow('10.0.0.1', room=True) for _ in range(500))
    assert [limits.allow('10.0.0.2') for _ in range(130)].count(True) == 120
    # The account bucket is independent of the address.
    assert all(limits.allow_account('acc-1') for _ in range(RequestLimits.ROOM_ACCOUNT_LIMIT))
    assert not limits.allow_account('acc-1') and limits.allow_account('acc-2')
    now[0] = 61.0
    assert limits.allow_account('acc-1')


def test_leave_room_http_both_channels_seat_game_and_host(pg_url, monkeypatch):
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)

    async def run():
        async with environment(pg_url) as (db, app):
            owner, _ = await guest_client(app)
            guests = [(await guest_client(app))[0] for _ in range(3)]
            tg, _ = await telegram_client(app, db)
            extra, _ = await guest_client(app)
            room_id, lobby_path = await make_table(owner)
            invite = (await post(owner, f'{R}/{room_id}/invites', {'expires_in_seconds': 3600, 'max_uses': 9})).json()
            everyone = [*guests, tg, extra]
            for index, client in enumerate(everyone):
                assert (await post(client, f'{R}/join', {'short_code': invite['short_code']})).status_code == 200
                assert (await post(client, lobby_path + '/join', {}, f'lj-{index}-000001')).status_code == 200

            async def leave(client):
                return (await client.get(f'{R}/{room_id}')).json()['membership_version']

            # The host cannot leave; the answer is a readable 403.
            mine = (await owner.get(f'{R}/{room_id}')).json()['membership_version']
            refused = await post(owner, f'{R}/{room_id}/leave', {'membership_version': mine})
            assert refused.status_code == 403 and 'Владелец' in refused.json()['detail']

            # Unstarted table: one call stands up and leaves the room.
            version = await leave(extra)
            gone = await post(extra, f'{R}/{room_id}/leave', {'membership_version': version})
            assert gone.status_code == 200 and gone.json() == {'left': True, 'table': 'unseated'}
            assert (await post(extra, f'{R}/{room_id}/leave', {'membership_version': version})).json() == {'left': False}
            assert (await extra.get(f'{R}/{room_id}')).status_code == 404
            assert len((await owner.get(lobby_path)).json()['lobby']['players']) == 5

            for index, client in enumerate([owner, *guests, tg]):
                current = (await client.get(lobby_path)).json()['lobby']
                assert (await post(client, lobby_path + '/ready', {'ready': True, 'expected_revision':
                        current['revision']}, f'lr-{index}-000001')).status_code == 200
            current = (await owner.get(lobby_path)).json()['lobby']
            started = (await post(owner, lobby_path + '/start', {'expected_revision': current['revision']},
                                  'lstart-00001')).json()['lobby']
            assert started['status'] == 'night' and len(started['players']) == 5

            # Night: the mafia has chosen; the Telegram detective (p5) leaves - the night still runs to its deadline.
            assert (await post(owner, f'{R}/{room_id}/mafia/action',
                               {'expected_revision': started['phase_revision'], 'target': 'p2'},
                               'lnight-00001')).json()['lobby']['status'] == 'night'
            version = await leave(tg)
            vanished = await post(tg, f'{R}/{room_id}/leave', {'membership_version': version})
            assert vanished.status_code == 200 and vanished.json() == {'left': True, 'table': 'vanished'}
            assert (await owner.get(lobby_path)).json()['lobby']['status'] == 'night'
            from tests.phase_helpers import end_phase
            assert (await end_phase(db, room_id=room_id))['status'] == 'day'
            day = (await owner.get(lobby_path)).json()['lobby']
            assert day['status'] == 'day' and day['players'][4]['alive'] is False
            assert {'type': 'vanished', 'round': 1, 'seat': 'p5', 'name': day['players'][4]['name']} in day['history']
            assert 'role' not in day['players'][4]
            assert (await tg.get(f'{R}/{room_id}/mafia/role')).status_code == 404
            assert (await post(tg, f'{R}/{room_id}/leave', {'membership_version': version})).json() == {'left': False}

            # A guest citizen leaves on the day: town 1 vs mafia 1, the mafia wins.
            version = await leave(guests[2])
            assert (await post(guests[2], f'{R}/{room_id}/leave', {'membership_version': version})).json() == {
                'left': True, 'table': 'vanished'}
            final = (await owner.get(lobby_path)).json()['lobby']
            assert final['status'] == 'finished' and final['winner'] == 'mafia'
            for client in (owner, *guests, tg, extra):
                await client.aclose()
    asyncio.run(run())


def test_room_routes_answer_429_503_and_fragment_links_instead_of_500(pg_url, monkeypatch):
    async def run():
        async with environment(pg_url) as (db, app):
            owner, _ = await guest_client(app)
            walker, _ = await guest_client(app)
            room_id, lobby_path = await make_table(owner)
            assert (await post(owner, f'{R}/{room_id}/open', {'open': True})).status_code == 200
            second_id = str(uuid4())
            assert (await post(owner, R, {'request_id': second_id, 'title': 'Второй стол'})).status_code == 200
            assert (await post(owner, f'{R}/{second_id}/mafia/lobby', {}, 'owner-create-2')).status_code == 200
            assert (await post(owner, f'{R}/{second_id}/open', {'open': True})).status_code == 200

            # The invitation link keeps the bearer code in the fragment, never in the query.
            invite = (await post(owner, f'{R}/{room_id}/invites', {'expires_in_seconds': 3600, 'max_uses': 5})).json()
            assert invite['web_url'] == f"{ORIGIN}/app#room={invite['invite_code']}"
            assert '?' not in invite['web_url'] and invite['startapp_param'] == 'room_' + invite['invite_code']

            # The membership limit answers 429 + Retry-After on every route that charges it.
            monkeypatch.setattr(room_limits, 'MEMBERSHIP_LIMIT', 1)
            entered = await post(walker, f'{R}/{room_id}/join-open', {}, 'w-open-0001')
            assert entered.status_code == 200, entered.text
            second = await post(walker, f'{R}/{second_id}/join-open', {}, 'w-open-0002')
            assert second.status_code == 429 and second.json()['code'] == 'rate_limited'
            assert int(second.headers['retry-after']) >= 1
            mine = (await walker.get(f'{R}/{room_id}')).json()
            left = await post(walker, f'{R}/{room_id}/leave', {'membership_version': mine['membership_version']})
            assert left.status_code == 429 and left.json()['code'] == 'rate_limited'
            assert int(left.headers['retry-after']) >= 1
            assert (await walker.get(f'{R}/{room_id}')).status_code == 200  # nothing was changed by the refusal
            monkeypatch.setattr(room_limits, 'MEMBERSHIP_LIMIT', 20)
            assert (await post(walker, f'{R}/{room_id}/leave', {'membership_version': mine['membership_version']})
                    ).status_code == 200

            # No free short code after the retries: a clear 503, not a 500.
            monkeypatch.setattr(room_limits, 'generate_short_code', lambda: 'AAAAAAAA')
            first_code = await post(owner, f'{R}/{room_id}/invites', {'expires_in_seconds': 3600, 'max_uses': 5})
            assert first_code.status_code == 200
            clash = await post(owner, f'{R}/{room_id}/invites', {'expires_in_seconds': 3600, 'max_uses': 5})
            assert clash.status_code == 503 and 'код' in clash.json()['detail']
            await owner.aclose()
            await walker.aclose()
    asyncio.run(run())


def test_code_failures_are_limited_per_client_address_over_http(pg_url, monkeypatch):
    monkeypatch.setattr(room_limits, 'CODE_FAIL_CLIENT_LIMIT', 3)
    monkeypatch.setattr(room_limits, 'CODE_FAIL_ACCOUNT_LIMIT', 50)

    async def run():
        async with environment(pg_url) as (db, app):
            owner, _ = await guest_client(app)
            room_id, _ = await make_table(owner)
            invite = (await post(owner, f'{R}/{room_id}/invites', {'expires_in_seconds': 3600, 'max_uses': 5})).json()
            guessers = [(await guest_client(app))[0] for _ in range(4)]
            for guesser in guessers[:3]:  # one account each, one address: the address pays
                assert (await post(guesser, f'{R}/join', {'short_code': 'ZZZZ-ZZZZ'})).status_code == 404
            blocked = await post(guessers[3], f'{R}/join', {'short_code': invite['short_code']})
            assert blocked.status_code == 429 and blocked.json()['code'] == 'rate_limited'
            async with db.transaction() as session:  # the address is stored hashed
                from sqlalchemy import select
                from storage.models import RoomJoinAttempt
                hashes = (await session.scalars(select(RoomJoinAttempt.client_hash).where(
                    RoomJoinAttempt.kind == 'code_fail'))).all()
                assert len(hashes) == 3 and len(set(hashes)) == 1 and '127.0.0.1' not in hashes[0]
                assert len(hashes[0]) == 64
    asyncio.run(run())


def test_garbage_session_cookies_do_not_get_the_wide_room_bucket(pg_url):
    async def run():
        async with environment(pg_url) as (db, app):
            good, _ = await guest_client(app)
            assert (await good.get(R)).status_code == 200  # a real session is remembered for this address
            # Wrong shape: strict bucket right away (120/min), never 1500.
            junk = new_client(app)
            junk.cookies.set('mqb_guest', 'x')
            statuses = [(await junk.get(R)).status_code for _ in range(125)]
            assert statuses.count(429) >= 4 and statuses[0] == 401
            # Right shape, wrong value: 401s are counted; after a few the address stops getting the wide bucket.
            forged = new_client(app)
            forged.cookies.set('mqb_guest', 'A' * 43)
            forged_statuses = [(await forged.get(R)).status_code for _ in range(RequestLimits.ROOM_AUTH_FAIL_LIMIT + 125)]
            assert forged_statuses[0] == 401 and 429 in forged_statuses
            assert forged_statuses.index(429) <= RequestLimits.ROOM_AUTH_FAIL_LIMIT + 125
            # The player behind the same address keeps working.
            assert (await good.get(R)).status_code == 200
            for client in (good, junk, forged):
                await client.aclose()
    asyncio.run(run())


def test_request_limits_demote_unknown_cookies_after_repeated_authentication_failures():
    now = [0.0]
    limits = RequestLimits(clock=lambda: now[0])
    good, other, junk = 'g' * 43, 'o' * 43, 'j' * 43
    assert limits.room_bucket_for('10.0.0.1', (good, None)) and limits.room_bucket_for('10.0.0.1', (None, other))
    assert not limits.room_bucket_for('10.0.0.1', (None, None))
    assert not limits.room_bucket_for('10.0.0.1', ('short', 'also short'))
    limits.note_authenticated('10.0.0.1', good)
    for _ in range(RequestLimits.ROOM_AUTH_FAIL_LIMIT):
        limits.note_auth_failure('10.0.0.1')
    assert limits.room_bucket_for('10.0.0.1', (good, None))  # accepted here recently: stays wide
    assert not limits.room_bucket_for('10.0.0.1', (junk, None))  # unknown cookie from a failing address: strict
    assert limits.room_bucket_for('10.0.0.2', (junk, None))  # another address is not affected
    now[0] = 61.0
    assert limits.room_bucket_for('10.0.0.1', (junk, None))  # a quiet minute heals it
    # allow_account keeps its own count without rebuilding the whole table on every call
    for index in range(50):
        limits.allow_account(f'acc-{index}')
    first = limits.accounts
    limits.allow_account('acc-0')
    assert limits.accounts is first
