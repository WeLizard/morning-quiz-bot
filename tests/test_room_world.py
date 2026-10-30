"""The story (world pack) of a Night City room: rules, projections and the HTTP command."""
import asyncio
from uuid import UUID, uuid4

import pytest

from domain.mafia import (join_lobby, new_room_lobby, normalized_lobby, public_lobby, restart_lobby, set_ready,
                          set_world, start_lobby)
from domain.night_worlds import AGE_MARKS, DEFAULT_WORLD, WORLD_IDS, world_age
from tests.test_room_telegram_channel import (R, environment, guest_client, hdr, pg_url, post)  # noqa: F401

ROOM = 'room-world-1'


def acc(number):
    return str(UUID(int=number))


def table(count=4):
    lobby = new_room_lobby(ROOM, acc(1), 'P1')
    for number in range(2, count + 1):
        lobby, _ = join_lobby(lobby, room_id=ROOM, account_id=acc(number), name=f'P{number}')
    for number in range(1, count + 1):
        lobby = set_ready(lobby, room_id=ROOM, account_id=acc(number), ready=True, expected_revision=lobby['revision'])
    return lobby


def pick(lobby, world, who=1, revision=None):
    return set_world(lobby, room_id=ROOM, account_id=acc(who), world=world,
                     expected_revision=lobby['revision'] if revision is None else revision)


def test_world_list_is_the_fifteen_known_ids_with_age_marks():
    assert len(WORLD_IDS) == 15 and len(set(WORLD_IDS)) == 15 and DEFAULT_WORLD in WORLD_IDS
    assert {'deep_choir', 'dead_air', 'velvet_circle', 'eternal_hotel'} <= set(WORLD_IDS)
    assert [world_age(world) for world in WORLD_IDS].count(16) == 2 and world_age(DEFAULT_WORLD) == 12
    assert set(AGE_MARKS) == {12, 16, 18} and {world_age(world) for world in WORLD_IDS} <= set(AGE_MARKS)
    assert {world for world in WORLD_IDS if world_age(world) == 16} == {'deep_choir', 'dead_air'}
    assert {world for world in WORLD_IDS if world_age(world) == 18} == {'velvet_circle', 'eternal_hotel'}
    assert world_age('no_such_world') == 12          # unknown counts as the default world
    lobby = table()
    assert public_lobby(lobby, room_id=ROOM, viewer_account_id=acc(1))['world_age'] == 12
    for world in ('deep_choir', 'dead_air'):         # accepted by the rules, mark in the projection
        picked = pick(lobby, world)
        assert picked['world'] == world and public_lobby(picked, room_id=ROOM, viewer_account_id=acc(1))['world_age'] == 16
    for world in ('velvet_circle', 'eternal_hotel'):  # 18+: the rules accept the id; age_ok is checked by the commands
        picked = pick(lobby, world)
        assert picked['world'] == world and public_lobby(picked, room_id=ROOM, viewer_account_id=acc(1))['world_age'] == 18


def test_the_18_plus_worlds_ask_for_age_ok_and_the_others_do_not():
    from domain.night_worlds import AgeConfirmRequired, require_age_ok
    for world in ('velvet_circle', 'eternal_hotel'):
        for answer in (None, False, 'yes', 1):
            with pytest.raises(AgeConfirmRequired):
                require_age_ok(world, answer)
        require_age_ok(world, True)
    for world in ('manor_lake', 'deep_choir', 'dead_air', 'no_such_world'):
        require_age_ok(world, None)


def test_lobby_defaults_to_the_pilot_world_and_projects_it():
    lobby = table()
    assert 'world' not in lobby  # the default is not stored: older states stay as they were
    assert public_lobby(lobby, room_id=ROOM, viewer_account_id=acc(2))['world'] == DEFAULT_WORLD
    assert new_room_lobby(ROOM, acc(1), 'P1', 'neon_city')['world'] == 'neon_city'
    assert 'world' not in new_room_lobby(ROOM, acc(1), 'P1', 'no_such_world')


def test_host_changes_the_world_and_the_revision_moves():
    lobby = table()
    revision = lobby['revision']
    changed = pick(lobby, 'night_express')
    assert changed['world'] == 'night_express' and changed['revision'] == revision + 1
    view = public_lobby(changed, room_id=ROOM, viewer_account_id=acc(3))
    assert view['world'] == 'night_express' and view['revision'] == revision + 1
    # the same world again is not a change
    same = pick(changed, 'night_express')
    assert same['revision'] == changed['revision']
    # back to the default drops the key but still counts as a change
    back = pick(changed, DEFAULT_WORLD)
    assert 'world' not in back and back['revision'] == changed['revision'] + 1
    assert public_lobby(back, room_id=ROOM, viewer_account_id=acc(1))['world'] == DEFAULT_WORLD


def test_world_change_refusals():
    lobby = table()
    with pytest.raises(PermissionError):
        pick(lobby, 'neon_city', who=2)
    with pytest.raises(ValueError, match='Неизвестный'):
        pick(lobby, 'atlantis')
    with pytest.raises(ValueError):
        pick(lobby, None)
    with pytest.raises(RuntimeError):
        pick(lobby, 'neon_city', revision=lobby['revision'] + 1)
    with pytest.raises(RuntimeError):
        pick(lobby, 'neon_city', revision=True)  # a bool is not a revision
    started = start_lobby(lobby, room_id=ROOM, account_id=acc(1), expected_revision=lobby['revision'])
    with pytest.raises(ValueError, match='до старта'):
        pick(started, 'neon_city')


def test_world_survives_start_and_rematch_and_ignores_garbage_in_state():
    lobby = pick(table(), 'circus')
    started = start_lobby(lobby, room_id=ROOM, account_id=acc(1), expected_revision=lobby['revision'])
    assert started['world'] == 'circus'
    assert public_lobby(started, room_id=ROOM, viewer_account_id=acc(1))['world'] == 'circus'
    finished = {**started, 'status': 'finished', 'winner': 'citizens'}
    again = restart_lobby(finished, room_id=ROOM, account_id=acc(1), expected_revision=finished['revision'])
    assert again['world'] == 'circus' and again['status'] == 'lobby'
    broken = {**lobby, 'world': '../../etc'}
    assert 'world' not in normalized_lobby(broken, room_id=ROOM)


def test_world_http_contract(pg_url):
    async def run():
        async with environment(pg_url) as (db, app):
            owner, _ = await guest_client(app)
            guest, _ = await guest_client(app)
            outsider, _ = await guest_client(app)
            room_id = str(uuid4())
            assert (await post(owner, R, {'request_id': room_id, 'title': 'Мир'})).json()['world'] == DEFAULT_WORLD
            lobby_path = f'{R}/{room_id}/mafia/lobby'
            world_path = f'{R}/{room_id}/world'
            created = await post(owner, lobby_path, {}, 'owner-create-1')
            assert created.status_code == 200 and created.json()['lobby']['world'] == DEFAULT_WORLD
            assert (await post(guest, f'{R}/{room_id}/open', {'open': True})).status_code == 404
            await post(owner, f'{R}/{room_id}/open', {'open': True})
            assert (await guest.get(f'{R}/open')).json()['items'][0]['world'] == DEFAULT_WORLD
            assert (await post(guest, f'{R}/{room_id}/join-open', {}, 'g-open-0001')).status_code == 200
            revision = (await owner.get(lobby_path)).json()['lobby']['revision']
            body = {'world': 'neon_city', 'expected_revision': revision}

            # Origin and CSRF are checked by the boundary; the command needs its Idempotency-Key.
            bare = await owner.post(world_path, json=body, headers={'Origin': hdr()['Origin']})
            assert bare.status_code == 403
            assert (await post(owner, world_path, body)).status_code == 400
            # Only the host; an outsider does not even learn that the room exists.
            refused = await post(guest, world_path, body, 'g-world-0001')
            assert refused.status_code == 403
            assert (await post(outsider, world_path, body, 'x-world-0001')).status_code == 404
            # Server-side list: unknown, malformed and extra fields are refused.
            for bad in ('atlantis', '', 'NEON_CITY', 5, None, '../neon_city'):
                assert (await post(owner, world_path, {'world': bad, 'expected_revision': revision},
                                   'o-bad-000001')).status_code == 400
            assert (await post(owner, world_path, {'world': 'neon_city'}, 'o-bad-000002')).status_code == 400
            assert (await post(owner, world_path, {**body, 'extra': 1}, 'o-bad-000003')).status_code == 400
            assert (await post(owner, world_path, {**body, 'expected_revision': -1}, 'o-bad-000004')).status_code == 400
            # A stale revision is a conflict and changes nothing.
            stale = await post(owner, world_path, {**body, 'expected_revision': revision + 5}, 'o-stale-00001')
            assert stale.status_code == 409
            assert (await owner.get(f'{R}/{room_id}')).json()['world'] == DEFAULT_WORLD

            changed = await post(owner, world_path, body, 'o-world-0001')
            assert changed.status_code == 200, changed.text
            answer = changed.json()
            assert answer['room']['world'] == 'neon_city' and answer['lobby']['world'] == 'neon_city'
            assert answer['lobby']['revision'] == revision + 1
            # A lost answer is retried with the same key: the same result, no second change.
            replay = await post(owner, world_path, body, 'o-world-0001')
            assert replay.status_code == 200 and replay.json() == answer
            assert (await owner.get(lobby_path)).json()['lobby']['revision'] == revision + 1
            # Everybody sees it: room, lobby (polled by the table) and the open list.
            assert (await guest.get(f'{R}/{room_id}')).json()['world'] == 'neon_city'
            assert (await guest.get(lobby_path)).json()['lobby']['world'] == 'neon_city'
            assert (await guest.get(f'{R}/open')).json()['items'][0]['world'] == 'neon_city'
            assert (await guest.get(f'{R}/open')).json()['items'][0]['world_age'] == 12
            # The two 16+ worlds are accepted by the server before their packs exist and carry the mark everywhere.
            current = (await owner.get(lobby_path)).json()['lobby']
            for index, adult in enumerate(('deep_choir', 'dead_air')):
                got = await post(owner, world_path, {'world': adult, 'expected_revision': current['revision']}, f'o-adult-000{index}')
                assert got.status_code == 200, got.text
                assert got.json()['room']['world_age'] == 16 and got.json()['lobby']['world_age'] == 16
                current = got.json()['lobby']
            assert (await guest.get(f'{R}/{room_id}')).json()['world_age'] == 16
            assert (await guest.get(f'{R}/open')).json()['items'][0]['world_age'] == 16
            back = await post(owner, world_path, {'world': 'neon_city', 'expected_revision': current['revision']}, 'o-adult-0009')
            assert back.status_code == 200 and back.json()['room']['world_age'] == 12
            assert [item['world'] for item in (await owner.get(R)).json()['items']] == ['neon_city']

            # Not after the night has started.
            for index, client in enumerate((owner, guest)):
                current = (await client.get(lobby_path)).json()['lobby']
                await post(client, lobby_path + '/ready', {'ready': True, 'expected_revision': current['revision']},
                           f'rd-{index}-00001')
            for index in range(2):
                extra, _ = await guest_client(app)
                assert (await post(extra, f'{R}/{room_id}/join-open', {}, f'e{index}-open-0001')).status_code == 200
                current = (await extra.get(lobby_path)).json()['lobby']
                await post(extra, lobby_path + '/ready', {'ready': True, 'expected_revision': current['revision']},
                           f'erd-{index}-0001')
            current = (await owner.get(lobby_path)).json()['lobby']
            started = await post(owner, lobby_path + '/start', {'expected_revision': current['revision']}, 'start-000001')
            assert started.status_code == 200 and started.json()['lobby']['world'] == 'neon_city'
            late = await post(owner, world_path, {'world': 'circus', 'expected_revision':
                              started.json()['lobby']['revision']}, 'o-world-0002')
            assert late.status_code == 409 and 'до старта' in late.json()['detail']
            assert (await owner.get(f'{R}/{room_id}')).json()['world'] == 'neon_city'
            for client in (owner, guest, outsider):
                await client.aclose()
    asyncio.run(run())


def test_age_18_worlds_need_age_ok_for_choosing_and_joining(pg_url, monkeypatch):
    """An 18+ world asks for the player's own confirmation (age_ok: true); 12 and 16 never do. Nothing is stored."""
    from domain import night_worlds
    monkeypatch.setitem(night_worlds.WORLD_AGES, 'test_adult', 18)

    async def run():
        async with environment(pg_url) as (db, app):
            owner, _ = await guest_client(app)
            a, _ = await guest_client(app)
            b, _ = await guest_client(app)
            c, _ = await guest_client(app)
            room_id = str(uuid4())
            await post(owner, R, {'request_id': room_id, 'title': 'Взрослый стол'})
            lobby_path = f'{R}/{room_id}/mafia/lobby'
            world_path = f'{R}/{room_id}/world'
            await post(owner, lobby_path, {}, 'owner-create-1')
            await post(owner, f'{R}/{room_id}/open', {'open': True})
            revision = (await owner.get(lobby_path)).json()['lobby']['revision']

            # 12 and 16: no field needed (the 16+ mark is a badge only); a wrong type is still refused.
            ok16 = await post(owner, world_path, {'world': 'deep_choir', 'expected_revision': revision}, 'o-w16-00001')
            assert ok16.status_code == 200 and ok16.json()['room']['world_age'] == 16
            revision = ok16.json()['lobby']['revision']
            ok12 = await post(owner, world_path, {'world': 'neon_city', 'expected_revision': revision, 'age_ok': True}, 'o-w12-00001')
            assert ok12.status_code == 200
            revision = ok12.json()['lobby']['revision']
            assert (await post(owner, world_path, {'world': 'test_adult', 'expected_revision': revision, 'age_ok': 'yes'}, 'o-bad-age-01')).status_code == 400

            # 18+: refused without age_ok (422, own code and a plain text), nothing changes.
            for body in ({'world': 'test_adult', 'expected_revision': revision},
                         {'world': 'test_adult', 'expected_revision': revision, 'age_ok': False}):
                refused = await post(owner, world_path, body, 'o-w18-' + str(len(body)))
                assert refused.status_code == 422 and refused.json()['code'] == 'age_confirm_required'
                assert 'тебе есть 18' in refused.json()['detail']
            assert (await owner.get(f'{R}/{room_id}')).json()['world'] == 'neon_city'
            ok = await post(owner, world_path, {'world': 'test_adult', 'expected_revision': revision, 'age_ok': True}, 'o-w18-ok-01')
            assert ok.status_code == 200 and ok.json()['room']['world'] == 'test_adult' and ok.json()['room']['world_age'] == 18
            assert 'age_ok' not in str(ok.json())

            # Joining an open 18+ table: the question first, the seat after the answer.
            no = await post(a, f'{R}/{room_id}/join-open', {}, 'a-join-00001')
            assert no.status_code == 422 and no.json()['code'] == 'age_confirm_required'
            assert (await a.get(f'{R}/{room_id}')).status_code == 404                  # no membership was left behind
            assert (await post(a, f'{R}/{room_id}/join-open', {'age_ok': 'x'}, 'a-join-00002')).status_code == 400
            yes = await post(a, f'{R}/{room_id}/join-open', {'age_ok': True}, 'a-join-00003')
            assert yes.status_code == 200 and yes.json()['joined']
            again = await post(a, f'{R}/{room_id}/join-open', {}, 'a-join-00004')       # already inside: nothing to confirm
            assert again.status_code == 200

            # Invitations: link token and short code.
            invite = (await post(owner, f'{R}/{room_id}/invites', {'expires_in_seconds': 3600, 'max_uses': 5})).json()
            refused = await post(b, f'{R}/join', {'invite_code': invite['invite_code']})
            assert refused.status_code == 422 and refused.json()['code'] == 'age_confirm_required'
            refused = await post(b, f'{R}/join', {'short_code': invite['short_code']})
            assert refused.status_code == 422 and refused.json()['code'] == 'age_confirm_required'
            assert (await b.get(f'{R}/{room_id}')).status_code == 404
            joined = await post(b, f'{R}/join', {'invite_code': invite['invite_code'], 'age_ok': True})
            assert joined.status_code == 200 and joined.json()['joined']
            assert (await post(c, f'{R}/join', {'short_code': invite['short_code'], 'age_ok': True})).status_code == 200
            assert (await post(c, f'{R}/join', {'age_ok': True})).status_code == 400        # a code is still required
            for client in (owner, a, b, c):
                await client.aclose()
    asyncio.run(run())


def test_age_ok_is_not_needed_for_12_and_16_joins(pg_url):
    async def run():
        async with environment(pg_url) as (db, app):
            owner, _ = await guest_client(app)
            a, _ = await guest_client(app)
            room_id = str(uuid4())
            await post(owner, R, {'request_id': room_id, 'title': 'Обычный стол'})
            lobby_path = f'{R}/{room_id}/mafia/lobby'
            await post(owner, lobby_path, {}, 'owner-create-1')
            await post(owner, f'{R}/{room_id}/open', {'open': True})
            revision = (await owner.get(lobby_path)).json()['lobby']['revision']
            assert (await post(owner, f'{R}/{room_id}/world', {'world': 'dead_air', 'expected_revision': revision}, 'o-w16-00001')).status_code == 200
            assert (await post(a, f'{R}/{room_id}/join-open', {}, 'a-join-00001')).status_code == 200
            await owner.aclose()
            await a.aclose()
    asyncio.run(run())
