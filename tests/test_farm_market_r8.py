"""Farm catalog r8: residents' reputation, the caravan (big order), daily contracts and their balance."""
import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from qw_farm import market
from qw_farm.catalog import (CROPS, ITEMS, LEVELS, MARKET, NPC_TASTES, NPCS, REP_NAMES, REP_POINTS, VERSION,
                             public_catalog, validate)
from qw_farm.domain import FarmError, apply, make_order, new_farm, project, reachable, validate_state
from qw_farm.expansion import settle, upgrade_state
from qw_farm.service import FarmService, Principal

STATIC = Path(__file__).resolve().parents[1] / 'qw_farm' / 'static'
T0 = 1_800_000_000                      # a fixed instant; Moscow day boundaries are computed from it
MSK = market.TZ_OFFSET


def midnight_msk(now):
    """First instant of the Moscow day that follows ``now``."""
    return (int((now + MSK) // 86400) + 1) * 86400 - MSK


def farm(xp=LEVELS[9], coins=10 ** 6, fid='00000000-0000-0000-0000-00000000a801', size=20):
    state = upgrade_state(new_farm(fid, 'Market', T0))
    state.update(size=size, xp=xp, coins=coins, starter_credit=0, objects=[], inventory={})
    state['market']['contracts'] = dict(day=-1, items=[])   # generated afresh for the level and layout under test
    state['progress'].update(day=10 ** 9, dew=10 ** 9)   # r9: no Morning dew (M1): exact reward expectations
    return state


def cmd(state, kind, data, at=T0):
    return apply(state, state, kind, data, at, f'{kind}-{at}-{len(state["events"])}')


def err(state, kind, data, at=T0):
    before = deepcopy(state)
    with pytest.raises(FarmError) as error:
        cmd(state, kind, data, at)
    assert state == before  # a refused command leaves the farm untouched
    return error.value.code


def give_order(state, npc, needs=None, coins=100, xp=10, special=False):
    order = dict(id='order_x', slot=0, npc=npc, title='Тест', needs=needs or {'wheat': 1}, coins=coins, xp=xp, skip_at=0)
    if special:
        order['special'] = True
    state['orders'][0] = order
    state['inventory']['wheat'] = state['inventory'].get('wheat', 0) + 50
    return order


def deliver(state, npc, at=T0, **kw):
    give_order(state, npc, **kw)
    before = state['coins']
    cmd(state, 'order', {'order': 'order_x'}, at)
    return state['coins'] - before


def add_plot_ready(state, n, crop='wheat', at=T0):
    spec = CROPS[crop]
    for i in range(n):
        state['objects'].append(dict(id=f'pl{i:03d}', type='plot', x=i % 20, y=i // 20 + 10, w=1, h=1, revision=0,
                                     crop=dict(id=crop, planted_at=at - spec['seconds'], ready_at=at, yield_qty=spec['yield_qty'],
                                               xp=spec['xp'], helped=False, watered=False, version=VERSION)))


# --- catalog ---------------------------------------------------------------------------------------------
def test_catalog_is_valid_versioned_and_exposed():
    validate()
    assert VERSION in {'farm-2026-10-r8', 'farm-2026-10-r9'}
    assert set(NPC_TASTES) == {n for n, _ in NPCS} and all(i in ITEMS for v in NPC_TASTES.values() for i in v)
    cat = public_catalog()['market']
    assert cat['rep_names'] == REP_NAMES and cat['rep_points'] == REP_POINTS and cat['rep_bonus'] == 5
    assert REP_NAMES[1] == 'Знакомый' and REP_NAMES[3] == 'Друг' and REP_NAMES[-1] == 'Лучший друг'
    assert MARKET['caravan']['level'] == 10 and 12 <= MARKET['caravan']['min_hours'] < MARKET['caravan']['max_hours'] <= 24


# --- reputation ------------------------------------------------------------------------------------------
def test_reputation_grows_with_delivered_orders_and_rewards_rise_five_percent_per_level_capped():
    state = farm()
    gains = []
    for n in range(1, REP_POINTS[-1] + 6):
        gains.append(deliver(state, 'Агата', coins=200))
        assert state['market']['rep']['Агата'] == n
    # level boundaries: the reward used for delivery #n is based on the level reached BEFORE it (n-1 points)
    for n, gain in enumerate(gains, start=1):
        lvl = market.rep_level(n - 1)
        assert gain == 200 * (100 + 5 * lvl) // 100, (n, gain)
    assert gains[0] == 200 and gains[-1] == 250        # +25% is the hard cap
    assert market.rep_state(state, 'Агата')['name'] == 'Лучший друг' and market.rep_state(state, 'Агата')['next_at'] is None
    assert state['market']['rep'].keys() == {'Агата'}   # other residents are unaffected
    assert market.rep_state(state, 'Филиныч')['bonus'] == 0
    assert any(e['kind'] == 'reputation' for e in state['events'])


def test_special_requests_unlock_only_with_reputation_and_use_the_residents_favourites():
    state = farm(xp=LEVELS[20])
    products = set(reachable(state))
    state['order_seq'] = 5
    seen = [make_order(state, 0, T0 + i) for i in range(400)]
    assert not any(o.get('special') for o in seen)       # nobody is a friend yet
    for npc in NPC_TASTES:
        state['market']['rep'][npc] = REP_POINTS[2]
    state['order_seq'] = 5
    orders = [make_order(state, 0, T0 + i) for i in range(400)]
    specials = [o for o in orders if o.get('special')]
    assert 30 <= len(specials) <= 160 and all(set(o['needs']) <= set(NPC_TASTES[o['npc']]) & products for o in specials)
    plain = [o for o in orders if not o.get('special')]
    assert plain and all('special' not in o for o in plain)
    # special ones pay +20% over a regular order for the same goods
    o = specials[0]
    price = sum(ITEMS[k]['price'] * q for k, q in o['needs'].items())
    import math
    assert o['coins'] == math.ceil((math.ceil(price * 1.45) + 6) * 1.2)
    # the tutorial orders never change
    fresh = farm()
    fresh['order_seq'] = 0
    fresh['market']['rep'] = {n: REP_POINTS[5] for n in NPC_TASTES}
    assert make_order(fresh, 0, T0)['needs'] == {'wheat': 6}


def test_special_delivery_gives_double_reputation():
    state = farm()
    deliver(state, 'Кошка Кая', special=True)
    assert state['market']['rep']['Кошка Кая'] == 2


# --- caravan ---------------------------------------------------------------------------------------------
def test_no_caravan_before_level_ten_then_one_arrives_with_valid_crates():
    low = farm(xp=LEVELS[8])
    settle(low, T0)
    assert low['market']['caravan'] is None
    state = farm()
    settle(state, T0)
    car = state['market']['caravan']
    assert car and 3 <= len(car['crates']) <= 6
    assert 12 * 3600 <= car['deadline'] - T0 <= 24 * 3600 and car['started_at'] == T0
    products = set(reachable(state))
    assert len({c['item'] for c in car['crates']}) == len(car['crates']) and {c['item'] for c in car['crates']} <= products
    assert all(1 <= c['qty'] <= 12 and not c['done'] for c in car['crates'])
    assert car['coins'] > car['value'] and car['npc'] in {n for n, _ in NPCS}
    snapshot = deepcopy(state)
    settle(state, T0 + 1)                                  # settling again is idempotent: one caravan at a time
    assert state['market']['caravan'] == snapshot['market']['caravan'] and state['market']['caravan_seq'] == 1


def test_caravan_partial_fill_complete_reward_and_cooldown():
    state = farm()
    settle(state, T0)
    car = deepcopy(state['market']['caravan'])
    for c in car['crates']:
        state['inventory'][c['item']] = c['qty']
    first = car['crates'][0]
    assert err(state, 'caravan_fill', {'crate': 99}) == 'invalid_crate'
    cmd(state, 'caravan_fill', {'crate': 0}, T0 + 60)
    assert state['inventory'][first['item']] == 0 and state['market']['caravan']['crates'][0]['done']
    assert err(state, 'caravan_fill', {'crate': 0}, T0 + 61) == 'crate_done'
    coins, xp = state['coins'], state['xp']
    for i in range(1, len(car['crates'])):
        assert state['market']['caravan'] is not None and state['coins'] == coins   # paid only at the end
        cmd(state, 'caravan_fill', {'crate': i}, T0 + 100 + i)
    bonus = market.boost(state, car['npc'], car['coins']) - car['coins']
    assert bonus == 0 or state['market']['rep']  # fresh reputation: no bonus on the first caravan
    assert state['coins'] - coins == car['coins'] and state['xp'] - xp == car['xp']
    assert state['market']['caravan'] is None and state['market']['caravans_done'] == 1
    last = state['market']['last_caravan']           # the card keeps showing the payout until the next caravan
    assert last['ok'] and last['npc'] == car['npc'] and last['coins'] == car['coins'] and last['xp'] >= car['xp'] and last['at'] == T0 + 100 + len(car['crates']) - 1
    assert state['market']['rep'][car['npc']] == 3
    assert state['market']['caravan_next_at'] == T0 + 100 + len(car['crates']) - 1 + 24 * 3600
    assert err(state, 'caravan_fill', {'crate': 0}, T0 + 200) == 'no_caravan'
    settle(state, T0 + 23 * 3600)
    assert state['market']['caravan'] is None               # still cooling down
    settle(state, state['market']['caravan_next_at'])
    assert state['market']['caravan']['id'] == 'caravan_1'
    validate_state(state)


def test_caravan_missing_goods_and_expiry_refund_delivered_crates_at_shop_price():
    state = farm()
    settle(state, T0)
    car = deepcopy(state['market']['caravan'])
    assert err(state, 'caravan_fill', {'crate': 0}) == 'missing_goods'
    c0 = car['crates'][0]
    state['inventory'][c0['item']] = c0['qty']
    cmd(state, 'caravan_fill', {'crate': 0}, T0 + 10)
    coins = state['coins']
    settle(state, car['deadline'] - 1)
    assert state['market']['caravan'] is not None
    # a later command settles first: the deadline is enforced by the server, not by the client
    with pytest.raises(FarmError) as late:      # (the service rolls the whole transaction back on error; here we inspect the state)
        cmd(state, 'caravan_fill', {'crate': 1}, car['deadline'] + 5)
    assert late.value.code == 'no_caravan'
    after = state['market']
    assert after['caravans_failed'] == 1 and after['caravans_done'] == 0
    assert after['last_caravan'] == dict(ok=False, npc=car['npc'], refund=ITEMS[c0['item']]['price'] * c0['qty'], at=car['deadline'])
    assert state['coins'] - coins == ITEMS[c0['item']]['price'] * c0['qty']
    assert after['caravan_next_at'] == car['deadline'] + 24 * 3600
    assert after['caravan'] is None
    settle(state, after['caravan_next_at'] + 5)
    assert state['market']['caravan']['started_at'] == after['caravan_next_at'] + 5


def test_caravan_expiry_with_nothing_delivered_costs_nothing():
    state = farm()
    settle(state, T0)
    car = state['market']['caravan']
    coins, inv = state['coins'], deepcopy(state['inventory'])
    settle(state, car['deadline'])
    assert state['coins'] == coins and state['inventory'] == inv and state['market']['caravan'] is None


def test_caravan_decor_gift_builds_for_free_once():
    state = farm()
    state['market']['decor_credits'] = ['bench']
    coins = state['coins']
    cmd(state, 'build', {'type': 'bench', 'x': 1, 'y': 1})
    assert state['coins'] == coins and state['market']['decor_credits'] == []
    cmd(state, 'build', {'type': 'bench', 'x': 3, 'y': 3})
    assert state['coins'] < coins                           # the second one is paid


def test_caravan_decor_chance_is_small_and_deterministic():
    hits = 0
    for i in range(300):
        state = farm(fid=f'00000000-0000-0000-0000-{i:012d}')
        settle(state, T0)
        hits += bool(state['market']['caravan']['decor'])
    assert 15 <= hits <= 90                                 # about 15%


# --- daily contracts -------------------------------------------------------------------------------------
def test_contracts_are_three_small_tasks_and_reset_by_moscow_day():
    state = farm(xp=LEVELS[3])
    settle(state, T0)
    items = state['market']['contracts']['items']
    assert len(items) == 3 and {c['kind'] for c in items} >= {'harvest', 'orders'}
    day = market.moscow_day(T0)
    assert state['market']['contracts']['day'] == day
    before = deepcopy(state['market']['contracts'])
    settle(state, midnight_msk(T0) - 1)                     # last second of the Moscow day: same contracts
    assert state['market']['contracts'] == before
    settle(state, midnight_msk(T0))                         # Moscow midnight: new day, fresh contracts
    assert state['market']['contracts']['day'] == day + 1
    assert [c['id'] for c in state['market']['contracts']['items']] != [c['id'] for c in before['items']]
    assert all(not c['claimed'] for c in state['market']['contracts']['items'])
    # 21:00 UTC is exactly Moscow midnight
    assert midnight_msk(T0) % 86400 == 21 * 3600


def test_contracts_are_locked_on_level_one_and_open_with_level_two():
    state = farm(xp=0)
    settle(state, T0)
    items = state['market']['contracts']['items']
    assert len(items) == 3                                   # prepared in advance: a level-up never changes a settled farm
    state['market']['counts'][market.contract_key(items[0])] = items[0]['base'] + items[0]['goal']
    assert err(state, 'contract_claim', {'contract': items[0]['id']}) == 'locked'
    state['xp'] = LEVELS[1]
    snapshot = deepcopy(state['market'])
    settle(state, T0 + 5)
    assert state['market'] == snapshot
    cmd(state, 'contract_claim', {'contract': items[0]['id']}, T0 + 6)


def test_harvest_contract_progress_claim_and_streak():
    state = farm(xp=LEVELS[3])
    settle(state, T0)
    harvest = next(c for c in state['market']['contracts']['items'] if c['kind'] == 'harvest')
    assert err(state, 'contract_claim', {'contract': harvest['id']}) == 'contract_incomplete'
    assert err(state, 'contract_claim', {'contract': 'nope'}) == 'not_found'
    spec = CROPS[harvest['item']]
    plots = -(-harvest['goal'] // spec['yield_qty'])
    add_plot_ready(state, plots, harvest['item'])
    cmd(state, 'collect_all', {})
    assert market.contract_progress(state, harvest) >= harvest['goal']
    coins, xp = state['coins'], state['xp']
    cmd(state, 'contract_claim', {'contract': harvest['id']})
    assert state['coins'] - coins == harvest['coins'] and state['xp'] - xp == harvest['xp']
    assert err(state, 'contract_claim', {'contract': harvest['id']}) == 'already_claimed'

    # finishing all three days in a row builds a mild streak bonus (+4% a day, max +20%)
    def finish_day(at):
        settle(state, at)
        for c in state['market']['contracts']['items']:
            state['market']['counts'][market.contract_key(c)] = state['market']['counts'].get(market.contract_key(c), 0) + c['goal']
            before = state['coins']
            cmd(state, 'contract_claim', {'contract': c['id']}, at)
            gain = state['coins'] - before
            assert gain >= c['coins']
        return state['market']['streak']['count']
    state['market']['contracts']['items'] = []; state['market']['contracts']['day'] = -1
    at, counts = T0 + 3600, []
    for _ in range(8):
        counts.append(finish_day(at))
        at = midnight_msk(at) + 60
    assert counts == [1, 2, 3, 4, 5, 6, 7, 8]
    assert market.streak_bonus(state, state['market']['contracts']['day']) == 20       # capped
    # a missed day resets the streak
    settle(state, midnight_msk(at) + 86400 * 2)
    assert market.streak_bonus(state, state['market']['contracts']['day']) == 0


def test_craft_contract_counts_collected_products():
    state = farm(xp=LEVELS[5])
    state['objects'].append(dict(id='bk', type='bakery', x=0, y=0, w=2, h=2, revision=0, level=1, jobs=[], animal=None, animal_job=None))
    settle(state, T0)
    craft = next(c for c in state['market']['contracts']['items'] if c['kind'] == 'craft')
    base = market.contract_progress(state, craft)
    state['market']['counts']['p:' + craft['item']] = state['market']['counts'].get('p:' + craft['item'], 0) + 1
    assert market.contract_progress(state, craft) == base + 1
    from qw_farm.catalog import RECIPES
    rid = next(r for r in RECIPES.values() if craft['item'] in r['outputs'] and r['building'] == 'bakery')
    state['inventory'].update({k: q for k, q in rid['inputs'].items()})
    cmd(state, 'queue', {'object': 'bk', 'recipe': rid['id']})
    cmd(state, 'collect', {'object': 'bk', 'job': state['objects'][0]['jobs'][0]['id']}, T0 + rid['seconds'] * 4)
    assert market.contract_progress(state, craft) >= base + 1 + rid['outputs'][craft['item']]


# --- idempotency and old saves -------------------------------------------------------------------------
class MemoryUnit:
    """The small slice of the persistence unit the service uses, in memory."""
    def __init__(self, account_id, state):
        self.account_id, self.farms, self.receipts, self.records = account_id, {state['id']: state}, {}, []

    async def lock(self, *keys): pass
    async def by_account(self, account_id): return next(iter(self.farms.values()))
    async def get(self, farm_id): return self.farms.get(farm_id)
    async def owner_account(self, farm_id): return self.account_id
    async def save(self, farm, account_id=None): self.farms[farm['id']] = farm
    async def receipt(self, account_id, key): return self.receipts.get((account_id, key))
    async def remember(self, account_id, key, fingerprint, result, now):
        self.receipts[(account_id, key)] = dict(fingerprint=fingerprint, result=result)
    async def record(self, actor, key, kind, before, after, now): self.records.append((key, kind))


def test_market_commands_are_idempotent_through_the_service():
    async def run():
        state = farm()
        settle(state, T0)
        car = state['market']['caravan']
        for c in car['crates']:
            state['inventory'][c['item']] = c['qty'] * 2
        unit = MemoryUnit('acc', state)
        clock = [T0 + 30]
        service = FarmService(unit, Principal('acc', 'Игрок'), clock=lambda: clock[0])
        first = await service.command('fill-0000-0001', 'caravan_fill', {'crate': 0})
        stock = unit.farms[state['id']]['inventory'][car['crates'][0]['item']]
        assert stock == car['crates'][0]['qty']
        replay = await service.command('fill-0000-0001', 'caravan_fill', {'crate': 0})
        assert replay == first and unit.farms[state['id']]['inventory'][car['crates'][0]['item']] == stock
        with pytest.raises(FarmError) as error:
            await service.command('fill-0000-0001', 'caravan_fill', {'crate': 1})
        assert error.value.code == 'key_reused'
        # finish through the service, then replay the finishing key: paid once
        for i in range(1, len(car['crates'])):
            done = await service.command(f'fill-0000-{i + 1:04d}', 'caravan_fill', {'crate': i})
        coins = unit.farms[state['id']]['coins']
        again = await service.command(f'fill-0000-{len(car["crates"]):04d}', 'caravan_fill', {'crate': len(car['crates']) - 1})
        assert again == done and unit.farms[state['id']]['coins'] == coins
        assert unit.farms[state['id']]['market']['caravans_done'] == 1
        # a contract claim is paid once as well
        farm_now = unit.farms[state['id']]
        c = farm_now['market']['contracts']['items'][2]            # the «orders» contract
        farm_now['market']['counts']['orders'] = farm_now['market']['counts'].get('orders', 0) + c['goal']
        got = await service.command('claim-0000-0001', 'contract_claim', {'contract': c['id']})
        coins = unit.farms[state['id']]['coins']
        assert await service.command('claim-0000-0001', 'contract_claim', {'contract': c['id']}) == got
        assert unit.farms[state['id']]['coins'] == coins
    asyncio.run(run())


def test_market_housekeeping_is_saved_without_an_economic_receipt_but_a_refund_is_recorded():
    async def run():
        state = farm()
        state['market']['contracts']['day'] = market.moscow_day(T0)
        unit = MemoryUnit('acc', state)
        clock = [T0]
        service = FarmService(unit, Principal('acc', 'Игрок'), clock=lambda: clock[0])
        await service.view()                                  # the caravan arrives: nothing to book
        car = unit.farms[state['id']]['market']['caravan']
        assert car and unit.records == []
        c0 = car['crates'][0]
        unit.farms[state['id']]['inventory'][c0['item']] = c0['qty']
        await service.command('fill-0000-0001', 'caravan_fill', {'crate': 0})
        records = len(unit.records)
        clock[0] = car['deadline'] + 1
        await service.view()                                  # expiry refunds coins: that is a real, recorded change
        assert unit.farms[state['id']]['market']['caravans_failed'] == 1 and len(unit.records) == records + 1
    asyncio.run(run())


def test_old_r7_save_without_market_loads_and_keeps_its_balances():
    state = farm(xp=LEVELS[11])
    old = deepcopy(state)
    old.pop('market')
    old['catalog'] = 'farm-2026-10-r7'
    old['orders'][0].update(needs={'wheat': 1})
    coins, inv, objs, orders = old['coins'], deepcopy(old['inventory']), deepcopy(old['objects']), deepcopy(old['orders'])
    upgrade_state(old)
    assert old['catalog'] == VERSION and old['market']['rep'] == {} and old['market']['caravan'] is None
    assert (old['coins'], old['inventory'], old['objects'], old['orders']) == (coins, inv, objs, orders)
    validate_state(old)
    settle(old, T0)                                         # first settle grants a caravan but never touches balances
    assert old['coins'] == coins and old['inventory'] == inv
    validate_state(old)
    old['inventory']['wheat'] = 5                           # old orders are still deliverable, no reputation needed
    gain = cmd(old, 'order', {'order': old['orders'][0]['id']})
    assert old['market']['rep']
    shown = project(old, old, T0)
    assert shown['market']['caravan'] and shown['market']['contracts']['items']
    other = farm(fid='00000000-0000-0000-0000-00000000a802')
    old['settings']['visibility'] = 'public'
    assert 'market' not in project(old, other, T0)          # visitors never see the market state


def test_visitors_cannot_use_market_commands():
    a = farm(); b = farm(fid='00000000-0000-0000-0000-00000000a802')
    with pytest.raises(FarmError) as error:
        apply(a, b, 'caravan_fill', {'crate': 0}, T0, 'k1-visitor')
    assert error.value.code == 'not_owner'
    with pytest.raises(FarmError):
        apply(a, a, 'contract_claim', {'contract': 'x', 'extra': 1}, T0, 'k2-visitor')   # strict schema


# --- balance ---------------------------------------------------------------------------------------------
def test_extra_income_stays_below_a_quarter_of_active_income_and_prints_the_table():
    rows = []
    for lv in (1, 2, 3, 5, 8, 10, 12, 15, 20, 25, 30):
        r = market.max_extra_daily(lv)
        rows.append((lv, r.get('caravan', 0), r['contracts'], r['reputation'], r['total'], r['reference'], r['share']))
    for lv in range(1, 31):
        assert market.max_extra_daily(lv)['share'] <= 0.25, lv
    print('\nlevel caravan contracts reputation total reference share')
    for row in rows:
        print(*row)


def test_generated_caravans_stay_inside_the_value_budget_at_every_level():
    for lv in range(10, 31):
        state = farm(xp=LEVELS[lv - 1])
        settle(state, T0)
        car = state['market']['caravan']
        assert 3 <= len(car['crates']) <= 6
        assert 0.5 * market.caravan_target(lv) <= car['value'] <= 2.2 * market.caravan_target(lv), (lv, car['value'], market.caravan_target(lv))
        assert car['coins'] <= car['value'] * 1.46 + 1


# --- UI contract -----------------------------------------------------------------------------------------
def test_ui_wires_the_market_commands_and_styles():
    app = (STATIC / 'app.js').read_text(encoding='utf-8')
    css = (STATIC / 'style.css').read_text(encoding='utf-8')
    for text in ("'caravan_fill'", "'contract_claim'", 'Жители', 'Обоз', 'Ежедневные контракты'):
        assert text in app, text
    for cls in ('caravan', 'crate', 'contract', 'rep-bar', 'residents'):
        assert cls in css, cls
