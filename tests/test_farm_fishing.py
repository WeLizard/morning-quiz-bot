"""Lake trips: server rewards, legacy saves and command receipt replay."""
import asyncio
from copy import deepcopy

import pytest

from qw_farm.catalog import FISHING_LEVEL, ITEMS, LEVELS, ROUTES, trip_kind
from qw_farm.domain import FarmError, apply, validate_state
from qw_farm.expansion import upgrade_state
from qw_farm.persistence import Unit
from tests.test_farm_automation_r7 import T0, farm
from tests.test_farm_platform import (
    accepted, command, environment, farm_pg_url, ledger, player, raw_farm, receipts,
)
from tests.test_farm_queue_r9 import players


FISHING_ROUTES = ('pond_bank', 'lake_inlet', 'river_bend')


def test_timber_path_is_independent_level_one_forest_trip():
    route = ROUTES['timber_path']
    assert ITEMS['wood']['name'] == 'Древесина'
    assert ITEMS['wood']['price'] == 8 and ITEMS['wood']['kind'] == 'forest'
    assert (route['level'], route['seconds'], route['cost'], route['inputs'],
            route['outputs'], route['xp'], route['specialty'], route['kind'], route['category']) == (
                1, 300, 4, {}, {'wood': 4}, 6, 'wood', 'forest', 'forest')
    state = fishing_farm('timber_path')
    before = deepcopy(state)
    act(state, 'start_trip', {'route': 'timber_path', 'guide': ''}, key='timber-start')
    trip = state['trips'][0]
    assert trip['ready_at'] == T0 + 300 and trip['outputs'] == {'wood': 4}
    assert state['coins'] == before['coins'] - 4
    act(state, 'collect_trip', {'trip': 'timber-start'}, at=T0 + 300)
    assert state['inventory']['wood'] == 4
    assert state['stats']['forages'] == 1 and state['stats']['fishing_trips'] == 0
    validate_state(state)


def test_old_forest_trip_without_kind_or_taken_still_refunds_original_route():
    state = fishing_farm('herb_meadow')
    state['inventory']['carrot'] = 1
    before = deepcopy(state)
    act(state, 'start_trip', {'route': 'herb_meadow', 'guide': ''}, key='old-forest')
    trip = state['trips'][0]
    del trip['kind'], trip['taken']
    assert trip_kind(trip) == 'forest'
    act(state, 'abort_trip', {'trip': 'old-forest'}, at=T0 + 30)
    assert state['coins'] == before['coins']
    assert state['inventory'] == before['inventory']
    assert state['trips'] == []


def fishing_farm(route='pond_bank', *, xp=None, fid=None):
    kwargs = {'coins': 1000, 'xp': LEVELS[ROUTES[route]['level'] - 1] if xp is None else xp}
    if fid is not None:
        kwargs['fid'] = fid
    state = farm(**kwargs)
    state['inventory'] = {'wheat': 10, 'bread': 10, 'corn': 10}
    return state


def act(state, kind, data, *, at=T0, key='fishing-command'):
    return apply(state, state, kind, data, at, key)


@pytest.mark.parametrize('route_id', FISHING_ROUTES)
def test_fishing_start_wait_collect_uses_server_cost_loot_and_separate_counter(route_id):
    state = fishing_farm(route_id)
    before = deepcopy(state)
    route = ROUTES[route_id]
    notice = act(state, 'start_trip', {'route': route_id, 'guide': ''}, key='fishing-start')
    trip = deepcopy(state['trips'][0])
    assert trip['kind'] == 'fishing' and trip['id'] == 'fishing-start'
    assert trip['outputs'] == route['outputs'] and trip['xp'] == route['xp']
    assert trip['ready_at'] == T0 + route['seconds']
    assert 'Рыбалка' in notice
    assert state['coins'] == before['coins'] - route['cost']
    assert all(state['inventory'][item] == before['inventory'][item] - qty
               for item, qty in route['inputs'].items())
    assert all(state['inventory'].get(item, 0) == 0 for item in route['outputs'])
    assert state['stats']['fishing_trips'] == state['stats']['forages'] == 0
    pending = deepcopy(state)
    with pytest.raises(FarmError) as error:
        act(state, 'collect_trip', {'trip': trip['id']}, at=trip['ready_at'] - 1)
    assert error.value.code == 'not_ready' and state == pending
    notice = act(state, 'collect_trip', {'trip': trip['id']}, at=trip['ready_at'])
    assert 'Улов' in notice and state['trips'] == []
    assert state['xp'] == before['xp'] + route['xp']
    assert all(state['inventory'][item] == qty for item, qty in route['outputs'].items())
    assert state['stats']['fishing_trips'] == 1 and state['stats']['forages'] == 0
    validate_state(state)
    collected = deepcopy(state)
    with pytest.raises(FarmError) as error:
        act(state, 'collect_trip', {'trip': trip['id']}, at=trip['ready_at'], key='second-collect')
    assert error.value.code == 'not_found' and state == collected


@pytest.mark.parametrize('route_id', FISHING_ROUTES)
def test_fishing_unlock_requires_exact_route_level(route_id):
    threshold = LEVELS[max(FISHING_LEVEL, ROUTES[route_id]['level']) - 1]
    state = fishing_farm(route_id, xp=threshold - 1)
    before = deepcopy(state)
    with pytest.raises(FarmError) as error:
        act(state, 'start_trip', {'route': route_id, 'guide': ''})
    assert error.value.code == 'locked' and state == before
    state['xp'] = threshold
    act(state, 'start_trip', {'route': route_id, 'guide': ''})
    assert len(state['trips']) == 1


def test_fishing_and_forest_share_two_slots_and_personal_activity():
    state = fishing_farm()
    for guide in ('hedgehog', 'squirrel'):
        state['helpers'][guide] = dict(acquired_at=T0, shift=None, total_runs=0)
    act(state, 'start_trip', {'route': 'pond_bank', 'guide': ''}, key='lake')
    before = deepcopy(state)
    with pytest.raises(FarmError) as error:
        act(state, 'start_trip', {'route': 'mushroom_wood', 'guide': ''}, key='solo-forest')
    assert error.value.code == 'trip_active' and state == before
    act(state, 'start_trip', {'route': 'mushroom_wood', 'guide': 'hedgehog'}, key='forest')
    before = deepcopy(state)
    with pytest.raises(FarmError) as error:
        act(state, 'start_trip', {'route': 'pond_bank', 'guide': 'squirrel'}, key='third-trip')
    assert error.value.code == 'trip_limit' and state == before
    for trip in deepcopy(state['trips']):
        act(state, 'collect_trip', {'trip': trip['id']}, at=T0 + 600, key='collect-' + trip['id'])
    assert state['stats']['fishing_trips'] == state['stats']['forages'] == 1


@pytest.mark.parametrize('route_id,counter', [('pond_bank', 'fishing_trips'), ('mushroom_wood', 'forages')])
def test_old_trip_without_kind_collects_stored_reward_in_the_correct_counter(route_id, counter):
    state = fishing_farm()
    act(state, 'start_trip', {'route': route_id, 'guide': ''}, key='legacy-trip')
    trip = state['trips'][0]
    del trip['kind']
    trip['outputs'] = {next(iter(trip['outputs'])): 7}
    trip['xp'] = 11
    stored = deepcopy(trip)
    xp = state['xp']
    assert trip_kind(trip) == ROUTES[route_id]['kind']
    act(state, 'collect_trip', {'trip': trip['id']}, at=trip['ready_at'])
    assert state['xp'] == xp + stored['xp']
    assert all(state['inventory'][item] == qty for item, qty in stored['outputs'].items())
    assert state['stats'][counter] == 1
    assert state['stats']['forages' if counter == 'fishing_trips' else 'fishing_trips'] == 0
    validate_state(state)


def test_old_farm_upgrade_adds_fishing_counter_without_reclassifying_existing_forages():
    state = fishing_farm()
    state['stats'].pop('fishing_trips')
    state['stats']['forages'] = 9
    before = deepcopy(state)
    upgrade_state(state)
    expected = deepcopy(before)
    expected['stats']['fishing_trips'] = 0
    assert state == expected
    assert upgrade_state(deepcopy(state)) == state


@pytest.mark.parametrize('legacy', [False, True])
def test_fishing_cancellation_refunds_bait_and_cost_without_completed_trip(legacy):
    state = fishing_farm()
    before = deepcopy(state)
    act(state, 'start_trip', {'route': 'pond_bank', 'guide': ''}, key='cancel-trip')
    if legacy:
        del state['trips'][0]['kind']
    notice = act(state, 'abort_trip', {'trip': 'cancel-trip'}, at=T0 + 60)
    assert 'рыбалка отменена' in notice
    for field in ('coins', 'inventory', 'xp', 'stats', 'starter_credit'):
        assert state[field] == before[field]
    assert state['trips'] == []


def test_early_return_gives_partial_fish_without_xp_or_completion_counter():
    state = fishing_farm()
    act(state, 'start_trip', {'route': 'pond_bank', 'guide': ''}, key='partial-trip')
    before = deepcopy(state)
    act(state, 'abort_trip', {'trip': 'partial-trip'}, at=T0 + 500)
    assert state['inventory']['crucian'] == 1  # floor(3 * 500/600 * 1/2)
    assert state['coins'] == before['coins'] and state['xp'] == before['xp']
    assert state['stats']['fishing_trips'] == state['stats']['forages'] == 0
    assert state['trips'] == []


def test_fishing_service_replays_start_and_collect_receipts_without_duplicate_rewards():
    async def run():
        clock = [T0]
        world, services = players('fisher', clock=clock)
        service = services['fisher']
        fid = (await service.open())['farm']['id']
        world.farms[fid] = fishing_farm(fid=fid)
        first = await service.command('service-start', 'start_trip', {'route': 'pond_bank', 'guide': ''})
        started = deepcopy(world.farms[fid])
        assert await service.command('service-start', 'start_trip', {'route': 'pond_bank', 'guide': ''}) == first
        assert world.farms[fid] == started and len(started['trips']) == 1
        with pytest.raises(FarmError) as error:
            await service.command('service-start', 'start_trip', {'route': 'lake_inlet', 'guide': ''})
        assert error.value.code == 'key_reused' and world.farms[fid] == started
        clock[0] = started['trips'][0]['ready_at']
        first = await service.command('service-collect', 'collect_trip', {'trip': 'service-start'})
        collected = deepcopy(world.farms[fid])
        assert await service.command('service-collect', 'collect_trip', {'trip': 'service-start'}) == first
        assert world.farms[fid] == collected
        assert collected['inventory']['crucian'] == 3 and collected['stats']['fishing_trips'] == 1
        assert collected['stats']['forages'] == 0
        with pytest.raises(FarmError) as error:
            await service.command('service-stale', 'collect_trip', {'trip': 'service-start'})
        assert error.value.code == 'not_found' and world.farms[fid] == collected
        assert len([record for record in world.records if record[1] == 'service-start']) == 1
        assert len([record for record in world.records if record[1] == 'service-collect']) == 1
    asyncio.run(run())


@pytest.mark.parametrize('identity', ['guest', 'telegram'])
def test_fishing_http_postgres_replay_and_stale_collect(farm_pg_url, identity):
    async def run():
        async with environment(farm_pg_url) as env, player(env, identity) as p:
            async with env.db.transaction() as session:
                state = fishing_farm(fid=p.farm_id)
                validate_state(state)
                await Unit(session, env.schema).save(state)
            first = await accepted(p, 'start_trip', {'route': 'pond_bank', 'guide': ''}, key='pg-fishing-start')
            started = await raw_farm(env, p)
            assert await accepted(p, 'start_trip', {'route': 'pond_bank', 'guide': ''}, key='pg-fishing-start') == first
            assert await raw_farm(env, p) == started
            early = await command(p, 'collect_trip', {'trip': 'pg-fishing-start'}, key='pg-fishing-early')
            assert early.status_code == 409 and early.json()['code'] == 'not_ready'
            assert not await receipts(env, p.account_id, 'pg-fishing-early')
            assert await raw_farm(env, p) == started
            env.now[0] = started['trips'][0]['ready_at']
            first = await accepted(p, 'collect_trip', {'trip': 'pg-fishing-start'}, key='pg-fishing-collect')
            collected = await raw_farm(env, p)
            assert await accepted(p, 'collect_trip', {'trip': 'pg-fishing-start'}, key='pg-fishing-collect') == first
            assert await raw_farm(env, p) == collected
            assert collected['inventory']['crucian'] == 3 and collected['stats']['fishing_trips'] == 1
            assert collected['stats']['forages'] == 0 and collected['trips'] == []
            for key in ('pg-fishing-start', 'pg-fishing-collect'):
                assert len(await receipts(env, p.account_id, key)) == 1
                assert len(await ledger(env, key=key)) == 1
            stale = await command(p, 'collect_trip', {'trip': 'pg-fishing-start'}, key='pg-fishing-stale')
            assert stale.status_code == 404 and stale.json()['code'] == 'not_found'
            assert await raw_farm(env, p) == collected
            assert not await receipts(env, p.account_id, 'pg-fishing-stale')
    asyncio.run(run())


def test_fishing_minigame_postgres_play_once_with_receipts(farm_pg_url):
    """trip_play over HTTP + PostgreSQL: the server replays the v2 log once; a replay of the same key changes nothing."""
    from tests.test_farm_trip_games import play_fish, end_s

    async def run():
        async with environment(farm_pg_url) as env, player(env, 'guest') as p:
            async with env.db.transaction() as session:
                state = fishing_farm(fid=p.farm_id)
                state['inventory']['bread'] = 2
                validate_state(state)
                await Unit(session, env.schema).save(state)
            await accepted(p, 'start_trip', {'route': 'pond_bank', 'guide': ''}, key='pg-fish-game-start')
            started = await raw_farm(env, p)
            trip = started['trips'][0]
            plan = trip['game']['plan']
            assert plan['v'] == 2 and trip['game']['state'] == 'open'
            log = play_fish(plan, bait='bread')
            env.now[0] = trip['started_at'] + end_s(plan, log)
            first = await accepted(p, 'trip_play', {'trip': trip['id'], 'log': log}, key='pg-fish-game-play')
            played = await raw_farm(env, p)
            game = played['trips'][0]['game']
            assert game['state'] == 'done' and game['q'] > 1000 and len(game['catch']) == 4
            assert played['inventory']['bread'] == 1 and sum(r['n'] for r in played['fish_journal'].values()) == 4
            assert await accepted(p, 'trip_play', {'trip': trip['id'], 'log': log}, key='pg-fish-game-play') == first
            assert await raw_farm(env, p) == played
            again = await command(p, 'trip_play', {'trip': trip['id'], 'log': log}, key='pg-fish-game-again')
            assert again.status_code == 409 and again.json()['code'] == 'already_played'
            assert await raw_farm(env, p) == played
            assert len(await receipts(env, p.account_id, 'pg-fish-game-play')) == 1
    asyncio.run(run())
