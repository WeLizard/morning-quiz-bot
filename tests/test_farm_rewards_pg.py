"""Exercise the operator queue and authenticated farm API with real PostgreSQL."""
import asyncio
from uuid import UUID

import pytest

from qw_farm.domain import FarmError
from qw_farm.persistence import Unit
from scripts.queue_farm_reward import queue_in
from tests.test_farm_platform import accepted, command, environment, farm_pg_url, ledger, player, raw_farm, receipts, view


def test_operator_queue_and_parallel_farm_claim(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as owner, player(env, 'telegram') as visitor:
            owner_farm, other_farm = UUID(owner.farm_id), UUID(visitor.farm_id)
            reward_id = 'season:test:leader'
            fields = dict(title='Опора деревни', message='За вклад в прошлом сезоне.',
                          coins=125, items={'wheat': 2}, decor=['fd_cup'])
            async with env.db.transaction() as session:
                unit = Unit(session, env.schema)
                farm = await unit.get(owner.farm_id)
                farm['settings']['visibility'] = 'public'
                await unit.save(farm)

            async def queue_recipient(farm_id):
                async with env.db.transaction() as session:
                    return await queue_in(session, farm_id, reward_id, fields, env.now[0])

            assert await queue_recipient(owner_farm) is True
            assert await queue_recipient(owner_farm) is False
            with pytest.raises(FarmError, match='закреплён'):
                await queue_recipient(other_farm)
            queued = [row for row in await ledger(env) if row['kind'] == 'farm_reward_queued']
            assert len(queued) == 1
            assert (await view(owner))['farm_rewards'][0]['id'] == reward_id
            assert 'farm_rewards' not in await view(visitor, owner.farm_id)
            forged = await command(visitor, 'claim_farm_reward', {'reward': reward_id}, target=owner.farm_id)
            assert forged.status_code == 403, forged.text

            data = {'reward': reward_id}
            keys = ('gift-tab-a', 'gift-tab-b')
            replies = await asyncio.gather(*(command(owner, 'claim_farm_reward', data, key=key) for key in keys))
            assert sorted(reply.status_code for reply in replies) == [200, 409]
            winner = next(index for index, reply in enumerate(replies) if reply.status_code == 200)
            assert await accepted(owner, 'claim_farm_reward', data, key=keys[winner]) == replies[winner].json()
            assert len(await receipts(env, owner.account_id, keys[winner])) == 1
            before, after = farm, await raw_farm(env, owner)
            assert after['coins'] == before['coins'] + 125
            assert after['inventory'].get('wheat', 0) == before['inventory'].get('wheat', 0) + 2
            public = await view(owner)
            assert public['farm_rewards'] == []
            assert public['farm_reward_decor'] == {'fd_cup': 1}

    asyncio.run(scenario())
