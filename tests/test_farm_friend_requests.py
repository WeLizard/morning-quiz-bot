"""Friend requests: persisted transitions, receipts and PostgreSQL races."""
import asyncio
import math
from uuid import UUID, uuid4

import sqlalchemy as sa

from qw_farm.catalog import ITEMS
from qw_farm.domain import validate_state
from qw_farm.domain import FarmError
from qw_farm.persistence import DemoDatabase, Unit
from qw_farm.service import FarmService, Principal
from tests.test_farm_platform import (accepted, command, environment, farm_pg_url, ledger,
                                     player, raw_farm, receipts, view)


async def prepare_farm(env, p, *, inventory=None):
    """Fixture-only progression and stock; commands still run through the HTTP API."""
    async with env.db.transaction() as db:
        unit = Unit(db, env.schema)
        farm = await unit.by_account(p.account_id)
        farm['stats']['orders'] = max(3, farm['stats']['orders'])
        farm['stats']['harvests'] = max(4, farm['stats']['harvests'])
        for item, qty in (inventory or {}).items():
            farm['inventory'][item] = qty
        validate_state(farm)
        await unit.save(farm)


async def neighbors(*players):
    for index, left in enumerate(players):
        for right in players[index + 1:]:
            await accepted(left, 'request_neighbor', {}, target=right.farm_id)
            await accepted(right, 'accept_neighbor', {}, target=left.farm_id)


async def age_neighborhood(env):
    # The contract requires an established 24-hour relationship.
    env.now[0] += 24 * 60 * 60 + 1


async def demo_pair(*, neighborhood_age=86401, start_time=1_700_000_000):
    db = DemoDatabase(':memory:')
    requester_account, giver_account = uuid4(), uuid4()
    with db.engine.begin() as connection:
        for account, label in ((requester_account, 'Requester'), (giver_account, 'Giver')):
            connection.execute(db.accounts.insert().values(
                id=account, name=label, recovery_hash=uuid4().hex))
    now = [start_time]

    def service(unit, account, label):
        return FarmService(unit, Principal(str(account), label), clock=lambda: now[0])

    async with db.transaction() as unit:
        requester = service(unit, requester_account, 'Requester')
        giver = service(unit, giver_account, 'Giver')
        await requester.open()
        await giver.open()
        requester_farm = await unit.by_account(requester_account)
        giver_farm = await unit.by_account(giver_account)
        requester_farm['neighbors'][giver_farm['id']] = {'name': 'Giver', 'status': 'accepted'}
        giver_farm['neighbors'][requester_farm['id']] = {'name': 'Requester', 'status': 'accepted'}
        requester_farm['stats'].update(orders=3, harvests=4)
        giver_farm['stats'].update(orders=3, harvests=4)
        giver_farm['inventory']['wheat'] = 4
        validate_state(requester_farm)
        validate_state(giver_farm)
        await unit.save(requester_farm)
        await unit.save(giver_farm)
        low, high = sorted((UUID(requester_farm['id']), UUID(giver_farm['id'])))
        await unit.execute(unit.t['neighbor_pairs'].insert().values(
            farm_low_id=low, farm_high_id=high, created_at=now[0] - neighborhood_age))
    return db, requester_account, giver_account, now, service


def test_pg_friend_request_free_delivery_acceptance_and_replay(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as requester, player(env) as giver:
            await neighbors(requester, giver)
            await age_neighborhood(env)
            await prepare_farm(env, requester)
            await prepare_farm(env, giver, inventory={'wheat': 4})

            before_requester = await raw_farm(env, requester)
            create_key = str(uuid4())
            create_payload = {'item': 'wheat', 'qty': 3, 'offer_kind': 'free'}
            created = await accepted(requester, 'request_create', create_payload, key=create_key)
            assert await accepted(requester, 'request_create', create_payload, key=create_key) == created
            request_id = created['request']
            assert request_id
            assert len(await receipts(env, requester.account_id, create_key)) == 1
            after_create = await raw_farm(env, requester)
            assert after_create['inventory'] == before_requester['inventory']
            assert after_create['coins'] == before_requester['coins']

            give_key = str(uuid4())
            given = await accepted(giver, 'request_give', {'request': request_id}, key=give_key)
            assert await accepted(giver, 'request_give', {'request': request_id}, key=give_key) == given
            assert len(await receipts(env, giver.account_id, give_key)) == 1
            assert (await raw_farm(env, giver))['inventory']['wheat'] == 1
            assert len(await ledger(env, key=f'request:{request_id}:delivered')) == 2
            pending = await view(requester)
            delivered = next(row for row in pending['friend_requests']['own'] if row['id'] == request_id)
            assert delivered['status'] == 'delivered'

            before_accept = await raw_farm(env, requester)
            accept_key = str(uuid4())
            settled = await accepted(requester, 'request_accept', {'request': request_id}, key=accept_key)
            assert await accepted(requester, 'request_accept', {'request': request_id}, key=accept_key) == settled
            assert len(await receipts(env, requester.account_id, accept_key)) == 1
            after_accept = await raw_farm(env, requester)
            assert after_accept['inventory']['wheat'] == before_accept['inventory'].get('wheat', 0) + 3
            assert after_accept['coins'] == before_accept['coins']
            assert after_accept['xp'] == before_accept['xp']
            after_giver = await raw_farm(env, giver)
            assert after_giver['stats']['helps'] == 1
            assert after_giver['friend_request_state']['good_deeds'] == 1
            assert len(await ledger(env, key=f'request:{request_id}:settled')) == 2
            closed = await command(requester, 'request_accept', {'request': request_id})
            assert closed.status_code in (400, 409)
            assert (await raw_farm(env, requester))['inventory']['wheat'] == after_accept['inventory']['wheat']

    asyncio.run(scenario())


def test_pg_friend_request_two_givers_only_one_reserves_goods(farm_pg_url):
    async def scenario():
        async with (environment(farm_pg_url) as env, player(env) as requester,
                    player(env) as first_giver, player(env) as second_giver):
            await neighbors(requester, first_giver, second_giver)
            await age_neighborhood(env)
            await prepare_farm(env, requester)
            await prepare_farm(env, first_giver, inventory={'wheat': 4})
            await prepare_farm(env, second_giver, inventory={'wheat': 4})
            created = await accepted(requester, 'request_create',
                                     {'item': 'wheat', 'qty': 3, 'offer_kind': 'free'})
            request_id = created['request']
            assert request_id

            replies = await asyncio.gather(
                command(first_giver, 'request_give', {'request': request_id}),
                command(second_giver, 'request_give', {'request': request_id}),
            )
            assert sum(response.status_code == 200 for response in replies) == 1
            assert all(response.status_code in (200, 400, 409) for response in replies)
            inventories = [(await raw_farm(env, p))['inventory']['wheat']
                           for p in (first_giver, second_giver)]
            assert sorted(inventories) == [1, 4]
            async with env.db.transaction() as db:
                row = (await db.execute(sa.select(env.schema['requests']).where(
                    env.schema['requests'].c.id == UUID(request_id)))).mappings().one()
                assert str(row['giver_farm']) in {first_giver.farm_id, second_giver.farm_id}

    asyncio.run(scenario())


def test_demo_friend_request_bound_terms_earned_coins_and_commission():
    async def scenario():
        db, requester_account, giver_account, now, service = await demo_pair()
        wheat_price = ITEMS['wheat']['price']
        async def expect_error(account, label, kind, data, code):
            try:
                async with db.transaction() as unit:
                    farm_service = service(unit, account, label)
                    await farm_service.command(uuid4().hex, kind, data)
            except FarmError as error:
                assert error.code == code
            else:
                raise AssertionError(f'{kind} unexpectedly succeeded')

        await expect_error(requester_account, 'Requester', 'request_create',
            {'item': 'dye_indigo', 'qty': 1, 'offer_kind': 'free'}, 'bound_item')
        await expect_error(requester_account, 'Requester', 'request_create',
            {'item': 'wheat', 'qty': 1, 'offer_kind': 'coins', 'offer_coins': wheat_price * 2},
            'request_offer_value')
        async with db.transaction() as unit:
            requester = service(unit, requester_account, 'Requester')
            created = await requester.command(uuid4().hex, 'request_create',
                {'item': 'wheat', 'qty': 1, 'offer_kind': 'coins', 'offer_coins': wheat_price})
            request_id = created['request']
        async with db.transaction() as unit:
            giver = service(unit, giver_account, 'Giver')
            await giver.command(uuid4().hex, 'request_give', {'request': request_id})
        await expect_error(requester_account, 'Requester', 'request_accept',
            {'request': request_id}, 'earned_coins')
        async with db.transaction() as unit:
            requester = service(unit, requester_account, 'Requester')
            farm = await requester.me()
            farm['coins'] += wheat_price
            await unit.save(farm)
        async with db.transaction() as unit:
            requester = service(unit, requester_account, 'Requester')
            before = await requester.me()
            await requester.command(uuid4().hex, 'request_accept', {'request': request_id})
            after = await requester.me()
            assert after['coins'] == before['coins'] - wheat_price
            assert after['inventory']['wheat'] == before['inventory'].get('wheat', 0) + 1
        async with db.transaction() as unit:
            giver = service(unit, giver_account, 'Giver')
            after = await giver.me()
            assert after['coins'] == 250 + wheat_price - math.ceil(wheat_price * 3 / 100)
            assert after['inventory']['wheat'] == 3
        db.engine.dispose()

    asyncio.run(scenario())


def test_demo_friend_request_age_and_gifts_share_delivery_quota():
    async def scenario():
        # 23:59 Moscow time; the next two minutes cross the daily quota boundary.
        boundary = 20_000 * 86400 + 20 * 3600 + 59 * 60
        db, requester_account, giver_account, now, service = await demo_pair(
            neighborhood_age=0, start_time=boundary)
        async with db.transaction() as unit:
            requester = service(unit, requester_account, 'Requester')
            created = await requester.command(uuid4().hex, 'request_create',
                {'item': 'wheat', 'qty': 1, 'offer_kind': 'free'})
            request_ids = [created['request']]
        try:
            async with db.transaction() as unit:
                giver = service(unit, giver_account, 'Giver')
                await giver.command(uuid4().hex, 'request_give', {'request': request_ids[0]})
        except FarmError as error:
            assert error.code == 'request_age'
        else:
            raise AssertionError('a new neighbor delivered a request before 24 hours')

        async with db.transaction() as unit:
            pairs = unit.t['neighbor_pairs']
            low, high = sorted((UUID((await unit.by_account(requester_account))['id']),
                                UUID((await unit.by_account(giver_account))['id'])))
            await unit.execute(sa.update(pairs).where(
                pairs.c.farm_low_id == low, pairs.c.farm_high_id == high).values(
                    created_at=now[0] - 86401))
        async with db.transaction() as unit:
            requester = service(unit, requester_account, 'Requester')
            for _ in range(2):
                created = await requester.command(uuid4().hex, 'request_create',
                    {'item': 'wheat', 'qty': 1, 'offer_kind': 'free'})
                request_ids.append(created['request'])
        for request_id in request_ids:
            async with db.transaction() as unit:
                giver = service(unit, giver_account, 'Giver')
                await giver.command(uuid4().hex, 'request_give', {'request': request_id})
        try:
            async with db.transaction() as unit:
                giver = service(unit, giver_account, 'Giver')
                farm = await giver.me()
                await giver.command(uuid4().hex, 'gift', {'item': 'wheat', 'qty': 1},
                                    target_id=farm['neighbors'].keys().__iter__().__next__())
        except FarmError as error:
            assert error.code == 'daily_limit'
        else:
            raise AssertionError('a fourth request/gift to one neighbor bypassed the shared cap')
        now[0] += 120
        async with db.transaction() as unit:
            giver = service(unit, giver_account, 'Giver')
            farm = await giver.me()
            peer_id = next(iter(farm['neighbors']))
            await giver.command(uuid4().hex, 'gift', {'item': 'wheat', 'qty': 1}, target_id=peer_id)
            assert (await giver.me())['inventory']['wheat'] == 0
        db.engine.dispose()

    asyncio.run(scenario())


def test_demo_friend_request_daily_value_and_open_limits():
    async def scenario():
        db, requester_account, _, now, service = await demo_pair()

        async def request_error(payload, code):
            try:
                async with db.transaction() as unit:
                    requester = service(unit, requester_account, 'Requester')
                    await requester.command(uuid4().hex, 'request_create', payload)
            except FarmError as error:
                assert error.code == code
            else:
                raise AssertionError(f'request_create unexpectedly bypassed {code}')

        await request_error({'item': 'wheat', 'qty': 20, 'offer_kind': 'free'}, 'request_value_limit')
        request_ids = []
        for _ in range(3):
            async with db.transaction() as unit:
                requester = service(unit, requester_account, 'Requester')
                created = await requester.command(uuid4().hex, 'request_create',
                    {'item': 'wheat', 'qty': 1, 'offer_kind': 'free'})
                request_ids.append(created['request'])
        async with db.transaction() as unit:
            requester_farm = await unit.by_account(requester_account)
            requests = unit.t['requests']
            await unit.execute(sa.update(requests).where(
                requests.c.requester_farm == UUID(requester_farm['id'])).values(
                    created_at=now[0] - 86400))
        await request_error({'item': 'wheat', 'qty': 1, 'offer_kind': 'free'}, 'request_open_limit')
        async with db.transaction() as unit:
            requester = service(unit, requester_account, 'Requester')
            await requester.command(uuid4().hex, 'request_cancel', {'request': request_ids[0]})
        for _ in range(3):
            async with db.transaction() as unit:
                requester = service(unit, requester_account, 'Requester')
                created = await requester.command(uuid4().hex, 'request_create',
                    {'item': 'wheat', 'qty': 1, 'offer_kind': 'free'})
            async with db.transaction() as unit:
                requester = service(unit, requester_account, 'Requester')
                await requester.command(uuid4().hex, 'request_cancel', {'request': created['request']})
        await request_error({'item': 'wheat', 'qty': 1, 'offer_kind': 'free'}, 'request_daily_limit')
        db.engine.dispose()

    asyncio.run(scenario())


def test_demo_neighbor_break_cancels_open_but_keeps_delivered_request():
    async def scenario():
        db, requester_account, giver_account, _, service = await demo_pair()
        async with db.transaction() as unit:
            requester = service(unit, requester_account, 'Requester')
            giver = service(unit, giver_account, 'Giver')
            giver_id = (await giver.me())['id']
            delivered = await requester.command(uuid4().hex, 'request_create',
                {'item': 'wheat', 'qty': 1, 'offer_kind': 'free', 'to': giver_id})
            open_request = await requester.command(uuid4().hex, 'request_create',
                {'item': 'wheat', 'qty': 1, 'offer_kind': 'free', 'to': giver_id})
        async with db.transaction() as unit:
            giver = service(unit, giver_account, 'Giver')
            await giver.command(uuid4().hex, 'request_give', {'request': delivered['request']})
        async with db.transaction() as unit:
            requester = service(unit, requester_account, 'Requester')
            await requester.command(uuid4().hex, 'remove_neighbor', {}, target_id=giver_id)
        async with db.transaction() as unit:
            requests = unit.t['requests']
            rows = (await unit.execute(sa.select(requests.c.id, requests.c.status).where(
                requests.c.id.in_([UUID(delivered['request']), UUID(open_request['request'])])))).all()
            assert {str(request_id): status for request_id, status in rows} == {
                delivered['request']: 'delivered', open_request['request']: 'cancelled'}
            giver = service(unit, giver_account, 'Giver')
            stock_before_accept = (await giver.me())['inventory']['wheat']
            requester = service(unit, requester_account, 'Requester')
            requester_stock_before_accept = (await requester.me())['inventory'].get('wheat', 0)
            await requester.command(uuid4().hex, 'request_accept', {'request': delivered['request']})
        async with db.transaction() as unit:
            requester = service(unit, requester_account, 'Requester')
            giver = service(unit, giver_account, 'Giver')
            assert (await requester.me())['inventory']['wheat'] == requester_stock_before_accept + 1
            assert (await giver.me())['inventory']['wheat'] == stock_before_accept
        db.engine.dispose()

    asyncio.run(scenario())


def test_pg_friend_request_accept_race_and_lazy_expiry_return(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as requester, player(env) as giver:
            await neighbors(requester, giver)
            await age_neighborhood(env)
            await prepare_farm(env, requester)
            await prepare_farm(env, giver, inventory={'wheat': 8})

            raced = await accepted(requester, 'request_create',
                                   {'item': 'wheat', 'qty': 2, 'offer_kind': 'free'})
            raced_id = raced['request']
            await accepted(giver, 'request_give', {'request': raced_id})
            wheat_before = (await raw_farm(env, requester))['inventory']['wheat']
            attempts = await asyncio.gather(
                command(requester, 'request_accept', {'request': raced_id}),
                command(requester, 'request_accept', {'request': raced_id}),
            )
            assert sum(response.status_code == 200 for response in attempts) == 1
            assert all(response.status_code in (200, 400, 409) for response in attempts)
            # The parcel is credited exactly once (a new farm already holds starter wheat).
            assert (await raw_farm(env, requester))['inventory']['wheat'] == wheat_before + 2
            assert (await raw_farm(env, giver))['stats']['helps'] == 1

            expiring = await accepted(requester, 'request_create',
                                      {'item': 'wheat', 'qty': 2, 'offer_kind': 'free'})
            expiring_id = expiring['request']
            before_giver = await raw_farm(env, giver)
            await accepted(giver, 'request_give', {'request': expiring_id})
            held = await raw_farm(env, giver)
            assert held['inventory']['wheat'] == before_giver['inventory']['wheat'] - 2
            env.now[0] += 72 * 60 * 60 + 1

            projected = await view(requester)
            returned = next(row for row in projected['friend_requests']['own'] if row['id'] == expiring_id)
            assert returned['status'] == 'returned'
            assert (await raw_farm(env, giver))['inventory']['wheat'] == before_giver['inventory']['wheat']
            assert len(await ledger(env, key=f'request:{expiring_id}:returned')) == 2

    asyncio.run(scenario())


def test_demo_merge_cancels_open_request_addressed_to_secondary():
    async def scenario():
        from qw_farm import friend_requests
        db, requester_account, secondary_account, now, service = await demo_pair()
        async with db.transaction() as unit:
            secondary = await unit.by_account(secondary_account)
            requester = service(unit, requester_account, 'Requester')
            request = await requester.command(uuid4().hex, 'request_create',
                {'item': 'wheat', 'qty': 1, 'offer_kind': 'free', 'to': secondary['id']})
        async with db.transaction() as unit:
            secondary = await unit.by_account(secondary_account)
            requester = await unit.by_account(requester_account)
            participants = await friend_requests.merge_participants(unit, [secondary['id']])
            assert participants == {requester['id'], secondary['id']}
            await unit.lock(*('farm:' + fid for fid in sorted(participants)))
            unit.friend_request_merge_farms = participants
            await friend_requests.merge_close(unit, requester_account, secondary_account, now[0])
            t = unit.t['requests']
            row = (await unit.execute(sa.select(t).where(t.c.id == UUID(request['request'])))).mappings().one()
            assert row['status'] == 'cancelled'
            assert (await unit.by_account(requester_account))['inventory'] == requester['inventory']
        db.engine.dispose()
    asyncio.run(scenario())


def test_demo_expiry_refuses_participant_added_after_lock_collection():
    async def scenario():
        from qw_farm import friend_requests
        db, requester_account, giver_account, _, service = await demo_pair()
        async with db.transaction() as unit:
            requester = service(unit, requester_account, 'Requester')
            request = await requester.command(uuid4().hex, 'request_create',
                {'item': 'wheat', 'qty': 1, 'offer_kind': 'free'})
            requester_id = (await requester.me())['id']
        async with db.transaction() as unit:
            giver = service(unit, giver_account, 'Giver')
            await giver.command(uuid4().hex, 'request_give', {'request': request['request']})
        async with db.transaction() as unit:
            locked = []
            async def track_lock(*keys):
                locked.extend(keys)
            unit.lock = track_lock
            try:
                # Models a delivery committed between expiry's participant query and sorted lock.
                await friend_requests.locked_row(unit, UUID(request['request']), prelocked={requester_id})
            except FarmError as error:
                assert error.code == 'request_retry'
            else:
                raise AssertionError('expiry acquired an uncollected participant lock')
            assert locked == []
            assert (await unit.by_account(giver_account))['inventory']['wheat'] == 3
        db.engine.dispose()
    asyncio.run(scenario())


def test_pg_reciprocal_visits_with_expiring_requests_do_not_deadlock(farm_pg_url):
    """Lazy expiry in the visit path locks the sorted union of participants; mutual visits must not deadlock."""
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as a, player(env) as b:
            await neighbors(a, b)
            await age_neighborhood(env)
            await prepare_farm(env, a, inventory={'wheat': 8})
            await prepare_farm(env, b, inventory={'wheat': 8})
            first = await accepted(a, 'request_create', {'item': 'wheat', 'qty': 1, 'offer_kind': 'free'})
            second = await accepted(b, 'request_create', {'item': 'wheat', 'qty': 1, 'offer_kind': 'free'})
            await accepted(b, 'request_give', {'request': first['request']})
            env.now[0] += 72 * 60 * 60 + 1  # a's parcel returns, b's open note expires
            await asyncio.wait_for(asyncio.gather(view(a, b.farm_id), view(b, a.farm_id),
                                                  view(a), view(b)), timeout=20)
            for p, rid, status in ((a, first['request'], 'returned'), (b, second['request'], 'expired')):
                mine = next(r for r in (await view(p))['friend_requests']['own'] if r['id'] == rid)
                assert mine['status'] == status
    asyncio.run(scenario())


def test_demo_friend_request_views_never_carry_account_ids():
    def keys(value):
        if isinstance(value, dict):
            for k, v in value.items():
                yield k
                yield from keys(v)
        elif isinstance(value, list):
            for v in value:
                yield from keys(v)

    async def scenario():
        db, requester_account, giver_account, now, service = await demo_pair()
        async with db.transaction() as unit:
            requester = service(unit, requester_account, 'Requester')
            await requester.command(uuid4().hex, 'request_create', {'item': 'wheat', 'qty': 1, 'offer_kind': 'free'})
        for account, label in ((requester_account, 'Requester'), (giver_account, 'Giver')):
            async with db.transaction() as unit:
                shown = (await service(unit, account, label).open())['farm']['friend_requests']
                assert shown and not [k for k in keys(shown) if k.endswith('_account')]
        db.engine.dispose()

    asyncio.run(scenario())
