"""Village errands and theft through real HTTP, transactions and persisted farm JSON."""
import asyncio
from copy import deepcopy
from uuid import uuid4

from qw_farm.domain import validate_state
from qw_farm.persistence import Unit
from tests.test_farm_platform import (API, FARM_HEADERS, accepted, command, environment,
                                      farm_pg_url, ledger, player, raw_farm, view)


async def presence(p, action, session):
    return await p.client.post(API + '/village/presence', params={'identity': p.identity},
                               headers=FARM_HEADERS, json={'action': action, 'session': session})


def test_pg_village_errands_and_theft(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as owner, player(env) as other:
            first = await view(owner)
            original_orders = deepcopy(first['orders'])
            async with env.db.transaction() as db:
                unit = Unit(db, env.schema)
                state = await unit.by_account(owner.account_id)
                state['inventory']['carrot'] = 4
                validate_state(state)
                await unit.save(state)
            before_bad = await raw_farm(env, owner)
            bad_quest = await command(owner, 'village_quest', {'npc': [], 'action': 'take'})
            bad_presence = await presence(owner, [], str(uuid4()))
            assert bad_quest.status_code == bad_presence.status_code == 422
            after_bad = await raw_farm(env, owner)
            assert after_bad['coins'] == before_bad['coins']
            assert after_bad['village_errands'] == before_bad['village_errands']
            for npc in ('Лиса Даша', 'Петух Олег'):
                await accepted(owner, 'village_quest', {'npc': npc, 'action': 'take'})
                key = str(uuid4())
                reply = await accepted(owner, 'village_quest', {'npc': npc, 'action': 'deliver'}, key=key)
                replay = await accepted(owner, 'village_quest', {'npc': npc, 'action': 'deliver'}, key=key)
                assert reply == replay
                second = await command(owner, 'village_quest', {'npc': npc, 'action': 'deliver'})
                assert second.status_code == 409 or second.status_code == 400
            persisted = await raw_farm(env, owner)
            assert persisted['orders'] == original_orders
            assert all(q['phase'] == 'done' for q in persisted['village_errands']['quests'].values())
            assert (await view(owner))['village_errands']['quests']['Лиса Даша'] == 'done'

            session = str(uuid4())
            at = env.now[0]
            initial = persisted['coins']
            assert (await presence(owner, 'enter', session)).json()['stolen'] == 0
            for step in (10, 20, 30, 40):
                env.now[0] = at + step
                assert (await presence(owner, 'pulse', session)).json()['stolen'] == 0
            env.now[0] = at + 50
            stolen = await presence(owner, 'pulse', session)
            assert stolen.status_code == 200, stolen.text
            assert stolen.json()['stolen'] == 2
            assert (await raw_farm(env, owner))['coins'] == initial - 2
            assert (await presence(owner, 'pulse', session)).json()['stolen'] == 0
            assert (await raw_farm(env, owner))['coins'] == initial - 2
            async with env.db.transaction() as db:
                unit = Unit(db, env.schema)
                public_owner = await unit.by_account(owner.account_id)
                public_owner['settings']['visibility'] = 'public'
                validate_state(public_owner)
                await unit.save(public_owner)
            foreign_view = await view(other, owner.farm_id)
            assert 'village_errands' not in foreign_view
            stranger = await view(other)
            assert 'village_errands' in stranger
            assert stranger['village_errands']['theft_total'] == 0
            assert (await raw_farm(env, other))['coins'] == 250
            assert (await presence(owner, 'leave', session)).status_code == 200
            env.now[0] = at + 500
            assert (await presence(owner, 'pulse', session)).json()['stolen'] == 0
    asyncio.run(scenario())


def test_pg_legacy_rooster_quest_migrates_on_view_and_keeps_receipts(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as owner:
            await view(owner)
            day = (env.now[0] + 10800) // 86400
            async with env.db.transaction() as db:
                unit = Unit(db, env.schema)
                state = await unit.by_account(owner.account_id)
                state['inventory']['wheat'] = 4
                state['village_errands']['quests'] = {'Петух Гриша': {'day': day, 'phase': 'active'}}
                await unit.save(state)  # fixture for a saved farm from before the rename
            entries_before = await ledger(env)
            projected = await view(owner)
            assert projected['village_errands']['quests'] == {'Петух Олег': 'active'}
            assert await ledger(env) == entries_before
            assert (await raw_farm(env, owner))['village_errands']['quests'] == {
                'Петух Олег': {'day': day, 'phase': 'active'}}
            before = await raw_farm(env, owner)
            key = str(uuid4())
            receipt = await accepted(owner, 'village_quest', {'npc': 'Петух Гриша', 'action': 'deliver'}, key=key)
            paid = await raw_farm(env, owner)
            assert paid['coins'] == before['coins'] + 12
            assert paid['village_errands']['quests']['Петух Олег']['phase'] == 'done'
            assert await accepted(owner, 'village_quest', {'npc': 'Петух Гриша', 'action': 'deliver'}, key=key) == receipt
            assert (await raw_farm(env, owner))['coins'] == paid['coins']
            assert len(await ledger(env, key=key)) == 1

            # A second old save with a completed quest must not offer it again today.
            async with env.db.transaction() as db:
                unit = Unit(db, env.schema)
                state = await unit.by_account(owner.account_id)
                state['village_errands']['quests']['Петух Гриша'] = state['village_errands']['quests'].pop('Петух Олег')
                await unit.save(state)
            assert (await view(owner))['village_errands']['quests'] == {'Петух Олег': 'done'}
            assert (await command(owner, 'village_quest', {'npc': 'Петух Олег', 'action': 'take'})).status_code in (400, 409)
            assert (await raw_farm(env, owner))['coins'] == paid['coins']
            env.now[0] += 86400
            assert (await view(owner))['village_errands']['quests']['Петух Олег'] == 'available'
            await accepted(owner, 'village_quest', {'npc': 'Петух Гриша', 'action': 'take'})
            assert (await raw_farm(env, owner))['village_errands']['quests']['Петух Олег']['phase'] == 'active'

    asyncio.run(scenario())
