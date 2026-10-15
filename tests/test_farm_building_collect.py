"""Collect only finished batches from the opened workshop, through common rules."""
from copy import deepcopy

import pytest

from qw_farm.catalog import RECIPES
from qw_farm.domain import FarmError, apply, validate_state
from qw_farm.expansion import make_job, take_job
from tests.test_farm_automation_r7 import T0, farm, add_building
from tests.test_farm_queue_r9 import players, run
from tests.test_farm_platform import (farm_pg_url, environment, player, accepted, command,
                                     raw_farm, view)  # noqa: F401 (fixture)
from qw_farm.persistence import Unit


def setup_workshops(state):
    recipe = next(r for r in RECIPES.values() if r['building'] == 'bakery')
    first = add_building(state, 'bakery', 'b1', 0, 0, level=2)
    second = add_building(state, 'bakery', 'b2', 3, 0, level=2)
    for obj, times in ((first, (T0 - 2, T0 - 1, T0 + 60)), (second, (T0 - 1,))):
        for i, ready_at in enumerate(times):
            job = make_job(obj, recipe, T0 - 1000, 1, f'{obj["id"]}-{i}', state)
            job['ready_at'] = ready_at
            job['starts_at'] = ready_at - recipe['seconds']
            obj['jobs'].append(job)
    return first, second


def test_collect_building_matches_single_job_rewards_and_keeps_other_work():
    state = farm()
    first, second = setup_workshops(state)
    before_second, pending = deepcopy(second), deepcopy(first['jobs'][-1])
    expected = deepcopy(state)
    for job in list(expected['objects'][0]['jobs'][:2]):
        take_job(expected, expected['objects'][0], job, T0)
    notice = apply(state, state, 'collect_building', {'object': 'b1'}, T0, 'bulk-ready')
    assert '2' in notice
    assert first['jobs'] == [pending] and second == before_second
    for key in ('inventory', 'xp', 'stats'):
        assert state[key] == expected[key]
    assert first['revision'] == 2
    validate_state(state)
    before = deepcopy(state)
    with pytest.raises(FarmError) as error:
        apply(state, state, 'collect_building', {'object': 'b1'}, T0, 'bulk-again')
    assert error.value.code == 'nothing_ready' and state == before


def test_collect_building_requires_owner_and_workshop():
    state = farm()
    setup_workshops(state)
    other = deepcopy(state)
    other['id'] = '00000000-0000-0000-0000-00000000f002'
    with pytest.raises(FarmError) as error:
        apply(state, other, 'collect_building', {'object': 'b1'}, T0, 'not-owner')
    assert error.value.code == 'not_owner'
    add_building(state, 'barn', 'barn1', 6, 0)
    with pytest.raises(FarmError) as error:
        apply(state, state, 'collect_building', {'object': 'barn1'}, T0, 'wrong-building')
    assert error.value.code == 'wrong_building'


def test_collect_building_receipt_retry_cannot_duplicate_outputs():
    async def go():
        clock = [T0]
        world, services = players('collector', clock=clock)
        service = services['collector']
        fid = (await service.open())['farm']['id']
        state = farm(fid=fid)
        setup_workshops(state)
        world.farms[fid] = state
        first = await service.command('building-collect-1', 'collect_building', {'object': 'b1'})
        saved = deepcopy(world.farms[fid])
        again = await service.command('building-collect-1', 'collect_building', {'object': 'b1'})
        assert first == again and world.farms[fid] == saved
        with pytest.raises(FarmError) as error:
            await service.command('building-collect-2', 'collect_building', {'object': 'b1'})
        assert error.value.code == 'nothing_ready' and world.farms[fid] == saved
        assert len([r for r in world.records if r[1] == 'building-collect-1']) == 1
    run(go())


def test_collect_building_postgres_transaction_replay_and_owner(farm_pg_url):
    import asyncio

    async def go():
        async with environment(farm_pg_url) as env:
            async with player(env) as owner, player(env) as stranger:
                async with env.db.transaction() as session:
                    unit = Unit(session, env.schema)
                    state = farm(fid=owner.farm_id)
                    first, second = setup_workshops(state)
                    for obj in (first, second):
                        for job in obj['jobs']:
                            job['starts_at'] += env.now[0] - T0
                            job['ready_at'] += env.now[0] - T0
                    validate_state(state)
                    await unit.save(state)
                before = await raw_farm(env, owner)
                denied = await command(stranger, 'collect_building', {'object': 'b1'}, target=owner.farm_id)
                assert denied.status_code == 403
                assert await raw_farm(env, owner) == before
                results = await asyncio.gather(*[
                    accepted(owner, 'collect_building', {'object': 'b1'}, key='pg-building-collect')
                    for _ in range(3)])
                assert results[0] == results[1] == results[2]
                after = await raw_farm(env, owner)
                assert len(after['objects'][0]['jobs']) == 1
                assert after['objects'][1] == before['objects'][1]
                assert after['stats']['crafts'] == before['stats']['crafts'] + 2
                replay = await accepted(owner, 'collect_building', {'object': 'b1'}, key='pg-building-collect')
                assert replay == results[0] and await raw_farm(env, owner) == after
                stale = await command(owner, 'collect_building', {'object': 'b1'})
                assert stale.status_code == 409 and 'nothing_ready' in stale.text
                assert await raw_farm(env, owner) == after
                assert (await view(owner))['inventory'] == after['inventory']
    run(go())
