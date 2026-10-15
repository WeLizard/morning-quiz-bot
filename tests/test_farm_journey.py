"""Real host-authenticated PostgreSQL vertical Farm journey, no Telegram I/O."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select

from qw_farm.domain import validate_state
from qw_farm.persistence import Unit
from storage.models import Account, MiniAppSession
from tests.test_farm_platform import (
    API, FARM_HEADERS, NOW, ORIGIN, TOKEN, accepted, be_neighbors, command,
    environment, farm_pg_url, ledger, player, raw_farm, receipts, signed, view,
)
from web.mini_app import MiniAppSettings, create_app


def test_farm_production_order_neighbors_and_new_session_preserve_progress(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env, player(env, 'telegram') as owner, player(env) as neighbor:
            assert owner.account_id != neighbor.account_id
            assert owner.farm_id != neighbor.farm_id
            # Fixture only: unlock the level-2 bakery and choose a deterministic
            # bread order. Clear starter wheat so all flour uses harvested grain.
            # No crops, production output, completed orders or social eligibility
            # are granted here: these are earned by the HTTP journey below.
            async with env.db.transaction() as session:
                unit = Unit(session, env.schema)
                farm = await unit.by_account(owner.account_id)
                before = deepcopy(farm)
                farm['xp'] = 20
                farm['inventory']['wheat'] = 0
                farm['orders'][0].update(needs={'bread': 1}, coins=49, xp=5)
                validate_state(farm)
                await unit.save(farm)
                await unit.record(owner.account_id, 'fixture-journey', 'fixture', before, farm, env.now[0])

            for plot in ('plot_3', 'plot_4'):
                await accepted(owner, 'plant', {'object': plot, 'crop': 'wheat', 'revision': 0})
            growing = await view(owner)
            assert growing['inventory']['wheat'] == 0
            assert growing['coins'] == 246
            env.now[0] += 31
            for plot, revision in (('plot_0', 0), ('plot_1', 0), ('plot_3', 1), ('plot_4', 1)):
                await accepted(owner, 'harvest', {'object': plot, 'revision': revision})
            harvested = await view(owner)
            assert harvested['inventory']['wheat'] == 12
            assert harvested['stats']['harvests'] == 4
            assert harvested['xp'] == 32  # 20 + 6 base XP, doubled by r9 Morning dew (M1) on a fresh farm

            bakery = 'journey-bakery'
            await accepted(owner, 'build', {'type': 'bakery', 'x': 0, 'y': 6}, key=bakery)
            for key in ('journey-flour-1', 'journey-flour-2'):
                await accepted(owner, 'queue', {'object': 'building_2', 'recipe': 'flour'}, key=key)
            queued = await view(owner)
            assert queued['inventory']['wheat'] == 8
            assert queued['inventory'].get('flour', 0) == 0
            mill = next(obj for obj in queued['objects'] if obj['id'] == 'building_2')
            env.now[0] = int(max(job['ready_at'] for job in mill['jobs'])) + 1
            for job in mill['jobs']:
                await accepted(owner, 'collect', {'object': 'building_2', 'job': job['id']})
            assert (await view(owner))['inventory']['flour'] == 2

            bread_job = 'journey-bread'
            await accepted(owner, 'queue', {'object': bakery, 'recipe': 'bread'}, key=bread_job)
            queued = await view(owner)
            oven = next(obj for obj in queued['objects'] if obj['id'] == bakery)
            assert queued['inventory']['flour'] == 0
            env.now[0] = int(oven['jobs'][0]['ready_at']) + 1
            await accepted(owner, 'collect', {'object': bakery, 'job': bread_job})
            baked = await view(owner)
            assert baked['inventory']['bread'] == 1 and baked['stats']['crafts'] == 3
            assert not next(obj for obj in baked['objects'] if obj['id'] == bakery)['jobs']
            balance_before_order = baked['coins']
            await accepted(owner, 'order', {'order': 'order_0'}, key='journey-order')
            delivered = await view(owner)
            assert delivered['inventory']['bread'] == 0
            assert delivered['coins'] == balance_before_order + 49 == 145
            assert delivered['stats']['orders'] == 1
            assert all(order['id'] != 'order_0' for order in delivered['orders'])
            entry = await ledger(env, key='journey-order')
            assert len(entry) == 1 and entry[0]['coins_delta'] == 49
            assert entry[0]['inventory_delta'] == {'bread': -1}

            invite = await owner.client.get(API + '/invite?identity=telegram')
            assert invite.status_code == 200, invite.text
            assert invite.json()['code'] == owner.farm_id
            neighbors = await neighbor.client.get(API + '/neighbors?identity=guest')
            assert neighbors.status_code == 200 and neighbors.json()['neighbors'] == []
            # Getting/copying an invite alone does not grant visit permissions.
            denied = await neighbor.client.get(API + '/farms/' + owner.farm_id + '?identity=guest')
            assert denied.status_code == 404
            await be_neighbors(owner, neighbor)
            visited = await view(neighbor, owner.farm_id)
            assert visited['id'] == owner.farm_id and visited['is_owner'] is False
            assert 'coins' not in visited and 'inventory' not in visited
            assert 'trips' not in visited and 'account_id' not in visited

            await accepted(owner, 'plant', {'object': 'plot_3', 'crop': 'carrot', 'revision': 2})
            planted = await view(owner)
            crop_before = next(obj for obj in planted['objects'] if obj['id'] == 'plot_3')['crop']
            await accepted(neighbor, 'help', {'object': 'plot_3', 'revision': 3}, target=owner.farm_id,
                           key='journey-help')
            watered = await view(owner)
            plot = next(obj for obj in watered['objects'] if obj['id'] == 'plot_3')
            assert plot['crop']['helped'] and plot['crop']['ready_at'] < crop_before['ready_at']
            assert plot['revision'] == 4
            assert (await view(neighbor))['stats']['helps'] == 1

            rejected = await command(neighbor, 'prank', {}, target=owner.farm_id, key='journey-no-consent')
            assert rejected.status_code == 403
            assert not await receipts(env, neighbor.account_id, 'journey-no-consent')
            for p in (owner, neighbor):
                farm = await view(p)
                await accepted(p, 'settings', {'name': farm['name'], **farm['settings'], 'allow_pranks': True})
                if p is owner:
                    rejected = await command(neighbor, 'prank', {}, target=owner.farm_id, key='journey-one-consent')
                    assert rejected.status_code == 403 and rejected.json()['code'] == 'mutual_consent'
            await accepted(neighbor, 'prank', {}, target=owner.farm_id, key='journey-goose')
            pranked = await view(owner)
            assert len(pranked['pranks']) == 1 and pranked['pranks'][0]['kind'] == 'goose'
            assert pranked['pranks'][0]['until'] == env.now[0] + 1200
            assert pranked['coins'] == watered['coins'] and pranked['inventory'] == watered['inventory']
            recipient_before = await view(neighbor)
            await accepted(owner, 'gift', {'item': 'wheat', 'qty': 1}, target=neighbor.farm_id,
                           key='journey-gift')
            gifted = await view(owner)
            recipient = await view(neighbor)
            assert gifted['inventory']['wheat'] == pranked['inventory']['wheat'] - 1
            assert recipient['inventory']['wheat'] == recipient_before['inventory']['wheat'] + 1
            assert gifted['stats']['gifts'] == 1
            entries = await ledger(env, key='journey-gift')
            assert len(entries) == 2 and sum(row['inventory_delta'].get('wheat', 0) for row in entries) == 0

            await accepted(owner, 'block', {}, target=neighbor.farm_id, key='journey-block')
            blocked_owner, blocked_neighbor = await raw_farm(env, owner), await raw_farm(env, neighbor)
            assert neighbor.farm_id in blocked_owner['blocked']
            assert neighbor.farm_id not in blocked_owner['neighbors']
            assert owner.farm_id not in blocked_neighbor['neighbors']
            denied = await neighbor.client.get(API + '/farms/' + owner.farm_id + '?identity=guest')
            assert denied.status_code == 404
            denied = await command(neighbor, 'help', {'object': 'plot_3', 'revision': 4},
                                   target=owner.farm_id, key='journey-blocked-help')
            assert denied.status_code == 404  # Block hides the target farm.
            assert not await receipts(env, neighbor.account_id, 'journey-blocked-help')
            assert await raw_farm(env, owner) == blocked_owner
            assert await raw_farm(env, neighbor) == blocked_neighbor

            # A fresh app/client and a genuinely new platform session must load
            # the same Account/Farm; no browser/local persistence is copied.
            old_token = owner.client.cookies.get('mqb_mini')
            restarted = create_app(database=env.db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True),
                                   clock=lambda: env.now[0])
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url=ORIGIN) as client:
                logged_in = await client.post('/api/mini/session', json={
                    'init_data': signed(owner.user_id, date=env.now[0], query_id=uuid4().hex)})
                assert logged_in.status_code == 200, logged_in.text
                assert client.cookies.get('mqb_mini') != old_token
                response = await client.post(API + '/start?identity=telegram', headers=FARM_HEADERS)
                assert response.status_code == 200 and response.json()['farm']['id'] == owner.farm_id
                restored = SimpleNamespace(client=client, identity='telegram', farm_id=owner.farm_id,
                                           account_id=owner.account_id)
                projected = await view(restored)
                assert projected['coins'] == blocked_owner['coins']
                assert projected['inventory'] == blocked_owner['inventory']
                assert projected['objects'] == blocked_owner['objects']
                assert projected['pranks'] == blocked_owner['pranks']
                assert projected['blocked'] == blocked_owner['blocked']
                assert projected['stats'] == blocked_owner['stats']
                assert await raw_farm(env, owner) == blocked_owner
            async with env.db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(Account)) == 2
                assert await session.scalar(select(func.count()).select_from(MiniAppSession)) == 2
                assert await session.scalar(select(func.count()).select_from(env.schema['states'])) == 2
            # Full economic history reconciles each saved scalar balance.
            entries = await ledger(env)
            for p, farm in ((owner, blocked_owner), (neighbor, blocked_neighbor)):
                own_entries = [row for row in entries if row['farm_id'] == UUID(p.farm_id)]
                assert sum(row['coins_delta'] for row in own_entries) == farm['coins']
                assert sum(row['xp_delta'] for row in own_entries) == farm['xp']
            assert env.now[0] > NOW
    asyncio.run(run())
