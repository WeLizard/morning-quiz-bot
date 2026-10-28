"""HTTP and PostgreSQL acceptance for atomic owner bulk repeats."""
import asyncio
from copy import deepcopy

from qw_farm.domain import validate_state
from qw_farm.persistence import Unit
from tests.test_farm_automation_r7 import add_building
from tests.test_farm_platform import (
    accepted, command, environment, farm_pg_url, ledger, player, raw_farm, receipts,
)


async def seed_mill(env, actor, wheat):
    async with env.db.transaction() as session:
        unit = Unit(session, env.schema)
        state = await unit.by_account(actor.account_id)
        before = deepcopy(state)
        state['objects'] = []
        mill = add_building(state, 'mill', 'bulk-mill', 0, 0, last_recipe='flour')
        mill['jobs'] = []
        state['inventory'] = {'wheat': wheat}
        validate_state(state)
        await unit.save(state)
        await unit.record(actor.account_id, 'fixture-bulk-mill', 'fixture', before, state, env.now[0])


def test_repeat_once_concurrent_old_tabs_spend_shared_stock_once_each(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as actor:
            await seed_mill(env, actor, 4)
            data = {'area': None}
            first_key, second_key = 'repeat-once-tab-a', 'repeat-once-tab-b'
            first, second = await asyncio.gather(
                accepted(actor, 'repeat_once', data, key=first_key),
                accepted(actor, 'repeat_once', data, key=second_key),
            )
            assert first['notice'].startswith('Поставлено партий: 1.')
            assert second['notice'].startswith('Поставлено партий: 1.')
            after = await raw_farm(env, actor)
            jobs = next(obj for obj in after['objects'] if obj['id'] == 'bulk-mill')['jobs']
            assert len(jobs) == 2 and len({job['id'] for job in jobs}) == 2
            assert all(job['manual'] is True and job['recipe'] == 'flour' for job in jobs)
            assert after['inventory'].get('wheat', 0) == 0
            assert await accepted(actor, 'repeat_once', data, key=first_key) == first
            assert await raw_farm(env, actor) == after
            for key in (first_key, second_key):
                assert len(await receipts(env, actor.account_id, key)) == 1
                assert len(await ledger(env, key=key)) == 1
    asyncio.run(scenario())


def test_fill_queues_http_retry_and_other_farm_denied(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as actor, player(env) as other:
            await seed_mill(env, actor, 6)
            forbidden = await command(actor, 'fill_queues', {'area': None}, target=other.farm_id,
                                      key='fill-other-farm')
            assert forbidden.status_code == 403 and forbidden.json()['code'] == 'not_owner'
            key = 'fill-own-queues-1'
            first = await accepted(actor, 'fill_queues', {'area': None}, key=key)
            assert first['notice'].startswith('Поставлено партий: 3.')
            after = await raw_farm(env, actor)
            jobs = next(obj for obj in after['objects'] if obj['id'] == 'bulk-mill')['jobs']
            assert len(jobs) == 3 and len({job['id'] for job in jobs}) == 3
            assert all(job['manual'] is True for job in jobs)
            assert after['inventory'].get('wheat', 0) == 0
            assert await accepted(actor, 'fill_queues', {'area': None}, key=key) == first
            assert await raw_farm(env, actor) == after
            assert len(await receipts(env, actor.account_id, key)) == 1
            assert len(await ledger(env, key=key)) == 1
    asyncio.run(scenario())
