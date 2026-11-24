"""Concurrent plantation collection through the HTTP adapter and PostgreSQL."""
import asyncio
from copy import deepcopy

import pytest

from qw_farm import catalog, progression
from qw_farm.domain import validate_state
from qw_farm.persistence import Unit
from tests.test_farm_plantation_game import walk
from tests.test_farm_platform import accepted, command, environment, farm_pg_url, ledger, player, raw_farm, receipts, view


@pytest.mark.parametrize('manual', [False, True])
def test_two_tabs_can_collect_a_plantation_cycle_only_once(farm_pg_url, manual):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as actor:
            async with env.db.transaction() as session:
                unit = Unit(session, env.schema)
                farm = await unit.by_account(actor.account_id)
                farm.update(coins=500_000, xp=catalog.LEVELS[31])
                validate_state(farm)
                await unit.save(farm)

            await accepted(actor, 'buy_plantation', {'step': 1})
            await accepted(actor, 'plant_plantation', {'plantation': 1, 'revision': 0, 'crop': 'vineyard'})
            before = await raw_farm(env, actor)
            cycle = before['plantations'][0]['cycle']
            env.now[0] = cycle['ready_at']
            data = {'plantation': 1, 'revision': 1}
            kind, stale, stock, xp = 'plantation_auto', 'stale_object', 53, 576
            revision = 1
            if manual:
                start_data = dict(data, op='harvest')
                start_key = 'plantation-manual-start'
                started = await accepted(actor, 'plantation_start', start_data, key=start_key)
                assert await accepted(actor, 'plantation_start', start_data, key=start_key) == started
                hectare = (await view(actor))['plantations'][0]
                run = hectare['run']
                assert run['id'] == start_key
                cell = run['targets'][0]
                data = dict(plantation=1, run=run['id'], path=walk(0, cell) + 'C' + walk(cell, 0) + 'X')
                kind, stale, stock, xp = 'plantation_finish', 'stale_plantation_run', 51, 550
                revision = hectare['revision']
                before = await raw_farm(env, actor)
            keys = ('plantation-harvest-tab-a', 'plantation-harvest-tab-b')
            replies = await asyncio.gather(*(command(actor, kind, data, key=key) for key in keys))
            assert sorted(reply.status_code for reply in replies) == [200, 409]
            winner = next(i for i, reply in enumerate(replies) if reply.status_code == 200)
            assert replies[1 - winner].json()['code'] == stale

            after = await raw_farm(env, actor)
            expected = deepcopy(before)
            progression.grant_xp(expected, xp, 'harvest', env.now[0], True, 2 * 86400)
            assert after['inventory']['grape'] == stock and after['xp'] == expected['xp']
            hectare = after['plantations'][0]
            assert hectare['harvests'] == 1 and hectare['revision'] == revision + 1 and 'run' not in hectare
            assert await accepted(actor, kind, data, key=keys[winner]) == replies[winner].json()
            assert await raw_farm(env, actor) == after
            assert len(await receipts(env, actor.account_id, keys[winner])) == 1
            assert len(await ledger(env, key=keys[winner])) == 1
            assert not await receipts(env, actor.account_id, keys[1 - winner])

    asyncio.run(scenario())
