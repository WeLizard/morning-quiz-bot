"""Concurrent plantation collection through the HTTP adapter and PostgreSQL."""
import asyncio
from copy import deepcopy

from qw_farm import catalog, progression
from qw_farm.domain import validate_state
from qw_farm.persistence import Unit
from tests.test_farm_platform import accepted, command, environment, farm_pg_url, ledger, player, raw_farm, receipts


def test_two_tabs_can_collect_a_plantation_cycle_only_once(farm_pg_url):
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
            keys = ('plantation-harvest-tab-a', 'plantation-harvest-tab-b')
            replies = await asyncio.gather(*(command(actor, 'plantation_auto', data, key=key) for key in keys))
            assert sorted(reply.status_code for reply in replies) == [200, 409]
            winner = next(i for i, reply in enumerate(replies) if reply.status_code == 200)
            assert replies[1 - winner].json()['code'] == 'stale_object'

            after = await raw_farm(env, actor)
            expected = deepcopy(before)
            progression.grant_xp(expected, 576, 'harvest', env.now[0], True, 2 * 86400)
            assert after['inventory']['grape'] == 41 and after['xp'] == expected['xp']
            hectare = after['plantations'][0]
            assert hectare['harvests'] == 1 and hectare['revision'] == data['revision'] + 1
            assert await accepted(actor, 'plantation_auto', data, key=keys[winner]) == replies[winner].json()
            assert await raw_farm(env, actor) == after
            assert len(await receipts(env, actor.account_id, keys[winner])) == 1
            assert len(await ledger(env, key=keys[winner])) == 1
            assert not await receipts(env, actor.account_id, keys[1 - winner])

    asyncio.run(scenario())
