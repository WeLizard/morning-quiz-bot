"""R9 feedback queue: dig up a planting, return early from the forest, neighbour reward, request limits."""
import asyncio
from copy import deepcopy
import math

import pytest

from qw_farm import invites, undo
from qw_farm.catalog import CROPS, HELPERS, LEVELS, ROUTES, income_ref
from qw_farm.domain import FarmError, apply, new_farm, project, validate_state
from qw_farm.expansion import upgrade_state
from qw_farm.service import FarmService, Principal
from tests.test_farm_automation_r7 import T0, add_plots, cmd, err, farm, obj
from tests.test_farm_invite_reward import World, Unit as TwinUnit, DAY, T0 as W0, run
from tests.test_farm_platform import farm_pg_url  # noqa: F401  (fixture)


def starter(coins=250, credit=250, xp=0):
    state = upgrade_state(new_farm('00000000-0000-0000-0000-00000000a001', 'Undo', T0))
    state.update(coins=coins, starter_credit=credit, xp=xp, objects=[], inventory={})
    state['progress'].update(day=10 ** 9, dew=10 ** 9)
    add_plots(state, 3, ready_at=None)
    return state


def plant(state, crop='corn', at=T0, plot='p0000'):
    cmd(state, 'plant', dict(object=plot, crop=crop, revision=obj(state, plot)['revision']), at)
    return obj(state, plot)


def dig(state, at, plot='p0000'):
    return cmd(state, 'dig_up', dict(object=plot, revision=obj(state, plot)['revision']), at)


# ------------------------------------------------------------------------------------------- 1. dig up a planting
def test_every_planting_path_records_the_price_paid():
    state = starter(coins=1000)
    assert plant(state)['crop']['cost'] == CROPS['corn']['cost']
    cmd(state, 'plant_many', dict(crop='carrot', area=None), T0)
    assert [o['crop']['cost'] for o in state['objects'] if o['id'] != 'p0000'] == [CROPS['carrot']['cost']] * 2
    from qw_farm.expansion import plant as machine_plant      # the helper behind the tractor / combine replanting
    add_plots(state, 1, ready_at=None, prefix='m')
    machine_plant(state, obj(state, 'm0000'), CROPS['wheat'], T0, 1)
    assert obj(state, 'm0000')['crop']['cost'] == CROPS['wheat']['cost']
    new = new_farm('00000000-0000-0000-0000-00000000a002', 'N', T0)
    assert all(o['crop']['cost'] == 0 for o in new['objects'] if o['type'] == 'plot' and o.get('crop'))  # the welcome plantings were free


def test_dig_up_full_refund_in_the_first_minute_and_half_later_without_xp():
    corn = CROPS['corn']['cost']
    for delay, expected in ((0, corn), (60, corn), (61, corn // 2), (299, corn // 2)):   # half of the price rounds down
        state = starter()
        plant(state)
        coins, xp = state['coins'], state['xp']
        revision = obj(state, 'p0000')['revision']
        text = dig(state, T0 + delay)
        plot = obj(state, 'p0000')
        assert plot['crop'] is None and plot['revision'] == revision + 1          # the bed is free at once
        assert state['coins'] == coins + expected and state['xp'] == xp            # no XP, no harvest
        assert ('полностью' in text) == (delay <= 60)
        validate_state(state)
        cmd(state, 'plant', dict(object='p0000', crop='wheat', revision=plot['revision']), T0 + delay)  # can plant again right away


def test_dig_up_returns_the_starter_gift_part_and_refuses_ripe_empty_or_stale():
    state = starter(coins=20, credit=20)
    plant(state)
    assert state['starter_credit'] == 20 - CROPS['corn']['cost']
    dig(state, T0 + 5)
    assert state['coins'] == 20 and state['starter_credit'] == 20                 # not turned into freely spendable coins
    assert err(state, 'dig_up', dict(object='p0000', revision=0), T0 + 6) == 'stale_object'   # already dug up (revision moved)
    assert err(state, 'dig_up', dict(object='p0000', revision=obj(state, 'p0000')['revision']), T0 + 6) == 'empty_plot'
    plant(state, 'wheat', T0 + 10)
    ripe = T0 + 10 + CROPS['wheat']['seconds']
    assert err(state, 'dig_up', dict(object='p0000', revision=obj(state, 'p0000')['revision']), ripe) == 'ripe'
    assert err(state, 'dig_up', dict(object='p0000'), T0) == 'invalid_command'


def test_old_planting_without_cost_uses_min_of_current_and_legacy_price(monkeypatch):
    state = starter()
    add_plots(state, 1, crop='corn', ready_at=T0 + 500, prefix='old')                 # saved before `cost` existed
    assert 'cost' not in obj(state, 'old0000')['crop']
    before = state['coins']
    cmd(state, 'dig_up', dict(object='old0000', revision=0), T0 + 10)
    assert state['coins'] == before + min(CROPS['corn']['cost'], undo.LEGACY_SEED_COST['corn'])   # the cheaper of the current and the r8 price
    add_plots(state, 1, crop='corn', ready_at=T0 + 500, prefix='old2', y0=5)
    monkeypatch.setitem(undo.LEGACY_SEED_COST, 'corn', 5)
    before = state['coins']
    cmd(state, 'dig_up', dict(object='old20500', revision=0), T0 + 10)
    assert state['coins'] == before + 5
    monkeypatch.setitem(undo.LEGACY_SEED_COST, 'corn', 999)                           # a legacy price above the current one is ignored
    assert undo.crop_cost(dict(id='corn', planted_at=0)) == CROPS['corn']['cost']
    assert undo.crop_cost(dict(id='gone_crop', planted_at=0)) == 0


def test_dig_up_is_idempotent_through_the_command_receipt():
    async def go():
        world, clock = World(), [W0]
        service = FarmService(PairUnit(world, 'a'), Principal('a', 'a'), clock=lambda: clock[0])
        farm_id = (await service.open())['farm']['id']
        state = world.farms[farm_id]
        plot = next(o for o in state['objects'] if o['type'] == 'plot' and not o['crop'])
        await service.command('plant-0001', 'plant', dict(object=plot['id'], crop='corn', revision=plot['revision']))
        coins = world.farms[farm_id]['coins']
        revision = next(o for o in world.farms[farm_id]['objects'] if o['id'] == plot['id'])['revision']
        payload = dict(object=plot['id'], revision=revision)
        first = await service.command('dig-0001', 'dig_up', payload)
        again = await service.command('dig-0001', 'dig_up', payload)             # a retry after a lost response
        assert again == first and world.farms[farm_id]['coins'] == coins + CROPS['corn']['cost']
        with pytest.raises(FarmError) as other:                                  # a NEW command on the same stale bed
            await service.command('dig-0002', 'dig_up', payload)
        assert other.value.code == 'stale_object' and world.farms[farm_id]['coins'] == coins + CROPS['corn']['cost']
        assert [r[2] for r in world.records if r[1] == 'dig-0001'] == ['dig_up']
    run(go())


# --------------------------------------------------------------------------------------- 2. early return from the forest
def trip_farm(route='old_grove', guide='', coins=100, bread=1):
    state = farm(coins=coins, xp=LEVELS[4])
    state['starter_credit'] = 0
    state['inventory'] = {'bread': bread, 'carrot': 1, 'oat_cookie': 1}
    if guide:
        state['helpers'][guide] = dict(acquired_at=T0, shift=None, total_runs=0)
    cmd(state, 'start_trip', dict(route=route, guide=guide), T0)
    return state


def test_trip_cancel_in_the_first_minute_returns_everything_taken():
    state = trip_farm()
    route = ROUTES['old_grove']
    assert state['coins'] == 100 - route['cost'] and state['inventory']['bread'] == 0
    trip = state['trips'][0]
    assert trip['taken'] == dict(coins=route['cost'], gift=0, items=route['inputs'])
    xp = state['xp']
    text = cmd(state, 'abort_trip', dict(trip=trip['id']), T0 + 60)
    assert state['trips'] == [] and state['coins'] == 100 and state['inventory']['bread'] == 1
    assert state['xp'] == xp and 'hazelnut' not in state['inventory'] and 'отменена' in text
    validate_state(state)
    cmd(state, 'start_trip', dict(route='old_grove', guide=''), T0 + 61)            # the basket is free again


def test_trip_early_return_later_pays_floor_of_half_of_elapsed_share_and_no_xp():
    state = trip_farm()
    trip = state['trips'][0]
    total = trip['ready_at'] - trip['started_at']
    coins, xp, bread = state['coins'], state['xp'], state['inventory']['bread']
    cmd(state, 'abort_trip', dict(trip=trip['id']), T0 + total // 2)
    # outputs hazelnut 6, mushroom 4, blackberry 3 -> floor(q * 1/2 * 1/2) = 1, 1, 0
    assert {k: v for k, v in state['inventory'].items() if k in ROUTES['old_grove']['outputs']} == {'hazelnut': 1, 'mushroom': 1}
    assert state['coins'] == coins and state['xp'] == xp and state['inventory']['bread'] == bread   # nothing taken comes back
    assert state['trips'] == [] and state['stats']['forages'] == 0
    validate_state(state)
    # shortly after the first minute: nothing was gathered yet, but the early return is still allowed
    state = trip_farm()
    text = cmd(state, 'abort_trip', dict(trip=state['trips'][0]['id']), T0 + 61)
    assert 'собрать ничего не удалось' in text and state['trips'] == []  # neutral wording: no form of address chosen


def test_trip_early_return_never_pays_secrets_and_guide_trips_work_the_same():
    state = trip_farm('herb_meadow', guide='hedgehog')
    trip = state['trips'][0]
    assert trip['guide'] == 'hedgehog'
    total = trip['ready_at'] - trip['started_at']
    cmd(state, 'abort_trip', dict(trip=trip['id']), T0 + total - 1)
    assert 'atlas' not in state['secrets'] and state['trips'] == []                    # a secret needs the finished walk
    state['inventory']['carrot'] = 1                                                   # the first walk took its carrot for good
    cmd(state, 'start_trip', dict(route='herb_meadow', guide='hedgehog'), T0 + 5000)   # the guide is free again
    assert state['trips'][0]['guide'] == 'hedgehog'
    cmd(state, 'abort_trip', dict(trip=state['trips'][0]['id']), T0 + 5010)            # cancelled within a minute: carrot back
    assert state['inventory']['carrot'] == 1 and state['trips'] == []


def test_trip_abort_rules_and_old_trips_without_taken():
    state = trip_farm()
    trip = state['trips'][0]
    assert err(state, 'abort_trip', dict(trip='nope'), T0 + 5) == 'not_found'
    assert err(state, 'abort_trip', dict(trip=trip['id']), trip['ready_at']) == 'trip_done'
    assert err(state, 'abort_trip', {}, T0 + 5) == 'invalid_command'
    del trip['taken']                                                                  # a trip saved before the field existed
    cmd(state, 'abort_trip', dict(trip=trip['id']), T0 + 30)
    assert state['coins'] == 100 and state['inventory']['bread'] == 1                  # derived from the route in the catalog


def test_trip_cancel_restores_the_starter_gift_part():
    state = farm(coins=20, xp=LEVELS[4])
    state['starter_credit'] = 20
    cmd(state, 'start_trip', dict(route='mushroom_wood', guide=''), T0)
    assert state['starter_credit'] == 20 - ROUTES['mushroom_wood']['cost']
    cmd(state, 'abort_trip', dict(trip=state['trips'][0]['id']), T0 + 3)
    assert state['coins'] == 20 and state['starter_credit'] == 20


# ------------------------------------------------------------------------------------------ 3. neighbour reward
class PairUnit(TwinUnit):
    def __init__(self, world, account):
        super().__init__(world, account)
        self.w.__dict__.setdefault('pairs', set())

    async def receipt(self, account_id, key):
        return self.w.__dict__.setdefault('receipts', {}).get((account_id, key))

    async def remember(self, account_id, key, fingerprint, result, now):
        self.w.__dict__.setdefault('receipts', {})[(account_id, key)] = dict(fingerprint=fingerprint, result=deepcopy(result))

    async def neighbor_pair_claim(self, a, b, now):
        key = frozenset((a, b))
        if key in self.w.pairs:
            return False
        self.w.pairs.add(key)
        return True


def players(*names, clock):
    world = World()
    return world, {n: FarmService(PairUnit(world, n), Principal(n, n), clock=lambda: clock[0]) for n in names}


async def meet(a, b, a_id, b_id, key):
    await a.command(key + '-request', 'request_neighbor', {}, b_id)
    return await b.command(key + '-accept', 'accept_neighbor', {}, a_id)


def test_neighbour_reward_is_half_a_day_of_early_income():
    assert invites.NEIGHBOR['reward'] == income_ref(1) // 2 == 550
    assert invites.NEIGHBOR['per_day'] * invites.NEIGHBOR['reward'] <= 3 * income_ref(1)


def test_both_neighbours_get_the_reward_once_per_pair_even_after_parting():
    async def go():
        clock = [W0]
        world, p = players('a', 'b', clock=clock)
        ids = {n: (await s.open())['farm']['id'] for n, s in p.items()}
        base = {n: world.farms[i]['coins'] for n, i in ids.items()}
        result = await meet(p['a'], p['b'], ids['a'], ids['b'], 'k1')
        reward = invites.NEIGHBOR['reward']
        assert 'Награда' in result['notice']
        assert result['neighbor_reward_paid'] is True
        assert {n: world.farms[i]['coins'] - base[n] for n, i in ids.items()} == {'a': reward, 'b': reward}
        for name, partner in (('a', 'b'), ('b', 'a')):
            own = (await p[name].view())['farm']
            assert own['neighbor_bonus']['rewards'] == [dict(id=ids[partner], partner_id=ids[partner],
                partner_name=partner, amount=reward, at=W0)]
        assert world.farms[ids['a']]['neighbor_bonus']['earned'] == reward
        assert [r for r in world.records if r[2] == 'accept_neighbor'] and sum(1 for r in world.records if r[3] == reward) == 2
        await p['a'].command('k1-remove', 'remove_neighbor', {}, ids['b'])                 # parted
        second = await meet(p['b'], p['a'], ids['b'], ids['a'], 'k2')                  # met again, the other way round
        assert 'neighbor_reward_paid' not in second
        assert {n: world.farms[i]['coins'] - base[n] for n, i in ids.items()} == {'a': reward, 'b': reward}
        assert len(world.farms[ids['a']]['neighbor_bonus']['rewards']) == 1
        view = await p['a'].view()
        assert view['invites']['neighbor'] == dict(reward=reward, per_day=invites.NEIGHBOR['per_day'], total_limit=invites.NEIGHBOR['total'],
                                                   today_left=invites.NEIGHBOR['per_day'] - 1, total=1, earned=reward)
    run(go())


def test_neighbour_reward_idempotent_command_and_no_self_invite():
    async def go():
        clock = [W0]
        world, p = players('a', 'b', clock=clock)
        ids = {n: (await s.open())['farm']['id'] for n, s in p.items()}
        with pytest.raises(FarmError) as own:
            await p['a'].command('self-0001', 'request_neighbor', {}, ids['a'])
        assert own.value.code == 'own_farm'
        await p['a'].command('request-1', 'request_neighbor', {}, ids['b'])
        first = await p['b'].command('accept-1', 'accept_neighbor', {}, ids['a'])
        coins = world.farms[ids['b']]['coins']
        again = await p['b'].command('accept-1', 'accept_neighbor', {}, ids['a'])
        assert again == first and world.farms[ids['b']]['coins'] == coins
    run(go())


def test_neighbour_reward_daily_limit_per_player_and_unpaid_pair_is_not_consumed():
    async def go():
        clock = [W0]
        names = ['host'] + [f'n{i}' for i in range(invites.NEIGHBOR['per_day'] + 1)]
        world, p = players(*names, clock=clock)
        ids = {n: (await s.open())['farm']['id'] for n, s in p.items()}
        reward = invites.NEIGHBOR['reward']
        host_base = world.farms[ids['host']]['coins']
        for i, name in enumerate(names[1:]):
            result = await meet(p[name], p['host'], ids[name], ids['host'], f'm{i}')
            assert ('neighbor_reward_paid' in result) == (i < invites.NEIGHBOR['per_day'])
        assert world.farms[ids['host']]['coins'] - host_base == invites.NEIGHBOR['per_day'] * reward      # the last one is over the limit
        late = names[-1]
        assert world.farms[ids[late]]['coins'] == 250                                                    # got nothing, was told why
        assert 'neighbor_bonus' not in world.farms[ids[late]]
        assert frozenset((ids[late], ids['host'])) not in world.pairs
        clock[0] += DAY                                                                                  # next Moscow day: room again
        await p[late].command('remove-key', 'remove_neighbor', {}, ids['host'])
        await meet(p[late], p['host'], ids[late], ids['host'], 'again')
        assert world.farms[ids[late]]['coins'] == 250 + reward
        assert frozenset((ids[late], ids['host'])) in world.pairs
    run(go())


def test_neighbour_reward_total_limit(monkeypatch):
    async def go():
        clock = [W0]
        monkeypatch.setitem(invites.NEIGHBOR, 'total', 1)
        world, p = players('a', 'b', 'c', clock=clock)
        ids = {n: (await s.open())['farm']['id'] for n, s in p.items()}
        await meet(p['a'], p['b'], ids['a'], ids['b'], 'x1')
        clock[0] += 3 * DAY
        base = world.farms[ids['a']]['coins']
        await meet(p['c'], p['a'], ids['c'], ids['a'], 'x2')
        assert world.farms[ids['a']]['coins'] == base and world.farms[ids['c']]['coins'] == 250
    run(go())


def test_postgres_neighbour_pair_is_claimed_once_for_the_unordered_pair(farm_pg_url):
    from sqlalchemy import func, select
    from tests.test_farm_platform import environment, player as http_player

    async def go():
        async with environment(farm_pg_url) as env:
            async with http_player(env) as a, http_player(env, user_id=981020000002) as b:
                from qw_farm.persistence import Unit
                async with env.db.transaction() as session:
                    unit = Unit(session, env.schema)
                    assert await unit.neighbor_pair_claim(a.farm_id, b.farm_id, 1.0) is True
                    assert await unit.neighbor_pair_claim(b.farm_id, a.farm_id, 2.0) is False       # swapped order, same pair
                async with env.db.transaction() as session:
                    table = env.schema['neighbor_pairs']
                    assert await session.scalar(select(func.count()).select_from(table)) == 1
    asyncio.run(go())


def test_postgres_http_accept_pays_both_farms_once(farm_pg_url):
    from tests.test_farm_platform import environment, player as http_player, raw_farm, command, accepted, view, API

    async def go():
        async with environment(farm_pg_url) as env:
            async with http_player(env) as a, http_player(env, user_id=981020000002) as b:
                base = {n: (await raw_farm(env, p))['coins'] for n, p in (('a', a), ('b', b))}
                await accepted(a, 'request_neighbor', {}, target=b.farm_id)
                key = 'neighbor-first-payment'
                paid = await accepted(b, 'accept_neighbor', {}, target=a.farm_id, key=key)
                assert paid['neighbor_reward_paid'] is True
                reward = invites.NEIGHBOR['reward']
                assert (await raw_farm(env, a))['coins'] == base['a'] + reward
                assert (await raw_farm(env, b))['coins'] == base['b'] + reward
                for player, partner in ((a, b), (b, a)):
                    own = await view(player)
                    record, = own['neighbor_bonus']['rewards']
                    assert record == {'id': partner.farm_id, 'partner_id': partner.farm_id,
                                      'partner_name': (await raw_farm(env, partner))['name'],
                                      'amount': reward, 'at': env.now[0]}
                assert 'neighbor_bonus' not in await view(a, b.farm_id)
                replay = await command(b, 'accept_neighbor', {}, target=a.farm_id, key=key)
                assert replay.json() == paid
                await accepted(a, 'remove_neighbor', {}, target=b.farm_id)
                await accepted(a, 'request_neighbor', {}, target=b.farm_id)
                again = await accepted(b, 'accept_neighbor', {}, target=a.farm_id)
                assert 'neighbor_reward_paid' not in again
                assert (await raw_farm(env, a))['coins'] == base['a'] + reward
                assert len((await view(a))['neighbor_bonus']['rewards']) == 1
                own = await command(a, 'request_neighbor', {}, target=a.farm_id)
                assert own.status_code == 422
    asyncio.run(go())


# ------------------------------------------------------------------------------------------------- 4. request limits
def test_mini_app_limits_fit_a_busy_farm_minute_and_stay_bounded():
    from web.mini_app import RequestLimits
    now = [0.0]
    limits = RequestLimits(clock=lambda: now[0])
    # 3 rounds of «plant 20 beds + harvest»: every action is one command and one state refresh, all within one minute
    for _ in range(3):
        for _ in range(21):
            assert limits.allow('1.2.3.4', farm_write=True) and limits.allow('1.2.3.4', frequent_read=True)
            now[0] += 0.8
    # ... and the other games of the same player keep their own bucket
    assert limits.allow('1.2.3.4')
    # the limits are NOT off: a runaway client is still stopped, per client
    now[0] += 120
    allowed = sum(limits.allow('9.9.9.9', farm_write=True) for _ in range(1000))
    assert 200 <= allowed <= 400
    assert limits.allow('8.8.8.8', farm_write=True)            # somebody else is not affected


def test_local_boundary_splits_reads_and_writes_and_tells_how_long_to_wait():
    from fastapi import FastAPI
    import httpx
    from qw_farm.api import install_boundary, LOCAL_LIMITS

    origin = 'http://testserver'
    app = FastAPI()
    install_boundary(app, origin)

    @app.post('/api/farm/v1/commands')
    async def command():
        return {'ok': True}

    @app.get('/api/farm/v1/me')
    async def me():
        return {'ok': True}

    async def go():
        headers = {'Origin': origin, 'X-QW-Farm': '1'}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
            for _ in range(3 * 21):                                     # a busy minute: 63 actions with a refresh after each
                assert (await client.post('/api/farm/v1/commands', headers=headers)).status_code == 200
                assert (await client.get('/api/farm/v1/me')).status_code == 200
            while True:                                                  # writes run out first, reads keep their own budget
                response = await client.post('/api/farm/v1/commands', headers=headers)
                if response.status_code == 429:
                    break
            assert response.json()['code'] == 'rate_limit' and 1 <= int(response.headers['retry-after']) <= 60
            assert (await client.get('/api/farm/v1/me')).status_code == 200
        assert LOCAL_LIMITS[True] < LOCAL_LIMITS[False]
    asyncio.run(go())


def test_shared_defaults_allow_a_busy_minute():
    from qw_farm.rate_limits import RateSettings
    settings = RateSettings('x' * 32)
    assert settings.account_write >= 150 and settings.account_read >= 2 * 63 and settings.ip_write >= settings.account_write
    assert settings.ip_read >= settings.account_read


@pytest.mark.parametrize('shared_mode', [False, True])
def test_postgres_http_typical_busy_minute_never_hits_the_limit(farm_pg_url, monkeypatch, shared_mode):
    """3 rounds of «plant 20 beds + collect» through HTTP, each action followed by the client's state refresh."""
    from tests.test_farm_platform import environment, player as http_player, command, view, raw_farm, API
    from qw_farm.persistence import Unit
    from qw_farm.domain import object_cells

    if shared_mode:
        monkeypatch.setenv('QW_FARM_SHARED_RATE_ENABLED', '1')
        monkeypatch.setenv('QW_FARM_RATE_SECRET', 'test-only-shared-farm-secret-00000002')

    async def go():
        async with environment(farm_pg_url) as env, http_player(env) as p:
            async with env.db.transaction() as session:
                unit = Unit(session, env.schema)
                state = await unit.by_account(p.account_id)
                state['objects'] = [o for o in state['objects'] if o['type'] != 'plot']
                used = set().union(*(object_cells(o) for o in state['objects'])) if state['objects'] else set()
                free = [(x, y) for y in range(state['size']) for x in range(state['size']) if (x, y) not in used][:20]
                for i, (x, y) in enumerate(free):
                    state['objects'].append(dict(id=f'bed{i:02d}', type='plot', x=x, y=y, w=1, h=1, revision=0, crop=None))
                state['coins'] = 5000
                state['revision'] += 1
                validate_state(state)
                await unit.save(state)
            seen = []
            for _ in range(3):
                me = await view(p)
                for bed in [o for o in me['objects'] if o['type'] == 'plot']:
                    response = await command(p, 'plant', {'object': bed['id'], 'crop': 'wheat', 'revision': bed['revision']})
                    seen.append(response.status_code)
                    seen.append((await p.client.get(API + '/me', params={'identity': p.identity})).status_code)
                env.now[0] += 60
                response = await command(p, 'collect_all', {})
                seen.append(response.status_code)
                seen.append((await p.client.get(API + '/me', params={'identity': p.identity})).status_code)
            assert set(seen) == {200}, [s for s in seen if s != 200]
            assert len(seen) == 3 * 42
    asyncio.run(go())
