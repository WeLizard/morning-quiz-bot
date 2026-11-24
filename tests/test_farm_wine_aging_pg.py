"""The cellar shelf is a real farm command, persisted and protected by PostgreSQL receipts."""
import asyncio
from uuid import uuid4

from qw_farm import catalog, economy
from qw_farm.persistence import Unit
from tests.test_farm_platform import accepted, command, environment, farm_pg_url, player, raw_farm, receipts, signed


def test_two_tabs_share_one_wine_batch_and_one_order(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env, 'telegram') as actor:
            async with env.db.transaction() as session:
                unit = Unit(session, env.schema)
                farm = await unit.by_account(actor.account_id)
                farm.update(coins=100_000, xp=catalog.LEVELS[31])
                farm['inventory']['wine_zero'] = 2
                await unit.save(farm)

            await accepted(actor, 'build', {'type': 'cellar', 'x': 0, 'y': 6})
            farm = await raw_farm(env, actor)
            cellar = next(obj for obj in farm['objects'] if obj['type'] == 'cellar')
            await accepted(actor, 'wine_age_start', {'object': cellar['id']}, key='cellar-start')
            farm = await raw_farm(env, actor)
            batch = farm['wine_aging']['batch']
            assert farm['inventory'].get('wine_zero', 0) == 0
            env.now[0] = batch['started_at'] + 30 * economy.DAY
            login = await actor.client.post('/api/mini/session', json={
                'init_data': signed(actor.user_id, date=env.now[0], query_id=uuid4().hex),
            })
            assert login.status_code == 200, login.text
            data = {'batch': batch['id'], 'item': 'wine_collectors'}
            keys = ('cellar-collect-a', 'cellar-collect-b')
            replies = await asyncio.gather(*(command(actor, 'wine_age_collect', data, key=key) for key in keys))
            assert sorted(reply.status_code for reply in replies) == [200, 409]
            winner = next(i for i, reply in enumerate(replies) if reply.status_code == 200)
            assert await accepted(actor, 'wine_age_collect', data, key=keys[winner]) == replies[winner].json()
            assert len(await receipts(env, actor.account_id, keys[winner])) == 1
            ready = await raw_farm(env, actor)
            assert ready['inventory']['wine_collectors'] == 2
            assert ready['wine_aging'] == {'batch': None, 'label_at': batch['started_at']}

            order = {'item': 'wine_collectors'}
            delivered = await accepted(actor, 'wine_age_order', order, key='cellar-order')
            assert await accepted(actor, 'wine_age_order', order, key='cellar-order') == delivered
            final = await raw_farm(env, actor)
            assert final['inventory'].get('wine_collectors', 0) == 0
            assert final['coins'] - ready['coins'] == 798

    asyncio.run(scenario())
