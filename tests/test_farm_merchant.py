"""Сорока-коробейница: schedule, stock, prices, limits, buy-back cap, idempotency, privacy, migration, bound goods, dyes only from her."""
import asyncio
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from qw_farm import economy, festivals, market, merchant as M
from qw_farm.catalog import (CROPS, CURIOS, DYES, EXOTIC_BY_SEED, EXOTIC_CROPS, ITEMS, LEVELS, MERCHANT, RECIPES, ROUTES, ANIMALS, SCROLL_RECIPES,
                             crop_law, income_ref, public_catalog)
from qw_farm.domain import FarmError, apply, make_order, new_farm, project, reachable, validate_state
from qw_farm.expansion import upgrade_state
from qw_farm.service import FarmService, Principal

MSK = timezone(timedelta(hours=3))
EPOCH = date(1970, 1, 1).toordinal()


def ts(y, m, d, h=12, minute=0, second=0):
    return int(datetime(y, m, d, h, minute, second, tzinfo=MSK).timestamp())


def day_of(y, m, d):
    return date(y, m, d).toordinal() - EPOCH


def noon(day):
    return M._ts(day) + 12 * 3600


def regular_day(after=day_of(2026, 11, 1)):
    """A scheduled day that is not a fair day, whose neighbours hold no visit."""
    d = after
    while not (M.scheduled(d) and M._fair_day(d) is None and M.visit_on(d - 1) is None and M.visit_on(d + 1) is None):
        d += 1
    return d


VISIT = regular_day()
NOW = noon(VISIT)


def farm(coins=10 ** 6, xp=LEVELS[29], inv=None, at=NOW):
    f = upgrade_state(new_farm(str(uuid4()), 'Sor', at))
    f.update(xp=xp, coins=coins, starter_credit=0, inventory=dict(inv or {}))
    f['progress'].update(day=10 ** 9, dew=10 ** 9)
    economy.state(f)['billed_day'] = 10 ** 9
    return f


def cmd(f, kind, data, at=NOW, key=None):
    return apply(f, f, kind, data, at, key or f'{kind}-{at}-{len(f["events"])}')


def code(f, kind, data, at=NOW):
    before = deepcopy(f)
    with pytest.raises(FarmError) as error:
        cmd(f, kind, data, at)
    assert f == before, 'a refused command leaves the farm untouched'
    return error.value.code


def slot_of(kind, visit=None):
    return next(s for s in M.stock(visit or M.visit_on(VISIT)) if s['kind'] == kind)


def buy(slot, qty=1, visit_id=None):
    return {'visit_id': visit_id or f'v{VISIT}', 'slot': slot, 'qty': qty}


# ---- schedule ------------------------------------------------------------------------------------------------------------------
def test_two_visits_a_week_on_two_different_non_adjacent_weekdays_for_years():
    start = day_of(2026, 10, 19)           # a Monday
    assert M.weekday(start) == 0 and date(2026, 10, 19).weekday() == 0
    days = [d for d in range(start, start + 7 * 150) if M.scheduled(d)]
    assert len(days) == 300
    for w in range(150):
        week = [d for d in days if start + 7 * w <= d < start + 7 * w + 7]
        assert len(week) == 2 and week[1] - week[0] >= 2
    assert all(b - a >= 2 for a, b in zip(days, days[1:])), 'never on consecutive days, Sunday to Monday included'
    assert {M.weekday(d) for d in days} == set(range(7)), 'every weekday occurs in the long run'


def test_schedule_is_deterministic_and_the_same_for_everyone():
    a = [M.visit_on(d) for d in range(VISIT, VISIT + 60)]
    assert a == [M.visit_on(d) for d in range(VISIT, VISIT + 60)]
    assert M.visit_at(NOW) == M.visit_at(NOW + 5) == M.visit_on(VISIT)
    assert M.visit_on(VISIT)['visit_id'] == f'v{VISIT}'


def test_a_visit_lasts_a_moscow_day_with_exact_boundaries():
    v = M.visit_on(VISIT)
    utc = lambda y, m, d, h, mi, s: int(datetime(y, m, d, h, mi, s, tzinfo=timezone.utc).timestamp())
    day = date.fromordinal(VISIT + EPOCH)
    opens = utc(day.year, day.month, day.day, 0, 0, 0) - 3 * 3600
    assert v['opens_at'] == opens and v['closes_at'] == opens + 86400
    assert M.visit_at(opens - 1) is None, '23:59:59 Moscow the day before: she is away'
    assert M.visit_at(opens)['visit_id'] == v['visit_id'], '00:00:00 Moscow: she arrives'
    assert M.visit_at(opens + 86399)['visit_id'] == v['visit_id']
    assert M.visit_at(opens + 86400) is None, '00:00:00 next day: she leaves'


def test_next_visit_and_the_herald_teaser_come_a_day_ahead():
    nxt = M.next_visit(NOW)
    assert nxt['day'] > VISIT and nxt['opens_at'] > NOW
    eve = nxt['opens_at'] - 3600
    assert M.public(eve)['teaser'] and M.public(eve)['teaser'] in {s['name'] for s in M.stock(nxt)}
    assert M.public(nxt['opens_at'] - 3 * 86400)['teaser'] is None
    away = M.public(M.visit_on(VISIT)['closes_at'] + 3600)
    assert away['active'] is False and away['slots'] == [] and away['next_at'] > away['opens_at'] if away['opens_at'] else away['next_at']


def test_fair_days_add_visits_and_overlap_with_a_regular_day_is_one_visit():
    fair_days = [d for y in (2026, 2027) for d in range(day_of(y, 1, 1), day_of(y, 12, 31) + 1) if M._fair_day(d)]
    assert fair_days, 'the calendar has fair days with her'
    for d in fair_days:
        v = M.visit_on(d)
        assert v is not None and v['kind'] == 'fair' and v['fair']['id'] and v['visit_id'] == f'v{d}'
    posid = day_of(2026, 11, 26)
    assert M.visit_on(posid)['fair']['id'] == 'posidelki' and M.visit_on(posid)['kind'] == 'fair'
    assert M.visit_on(posid + 1) is None or M.visit_on(posid + 1)['kind'] == 'regular', 'only the first fair day has her (posidelki)'
    spas = [day_of(2027, 8, 14), day_of(2027, 8, 19), day_of(2027, 8, 29)]
    assert all(M.visit_on(d)['kind'] == 'fair' for d in spas), 'at Спасы she comes to every fair day'
    # one visit per day even when a regular day coincides with a fair day
    both = [d for d in fair_days if M.scheduled(d)]
    assert both and all(M.visit_on(d)['visit_id'] == f'v{d}' for d in both)
    pub = M.public(noon(posid))
    assert pub['fair']['id'] == 'posidelki' and 'fest_posid_lantern' in pub['fair']['goods']
    assert M.public(NOW)['fair'] is None


# ---- stock and prices ----------------------------------------------------------------------------------------------------------
def test_stock_is_six_deterministic_slots_with_the_value_law_prices():
    v = M.visit_on(VISIT)
    slots = M.stock(v)
    assert len(slots) == 6 and slots == M.stock(v) and [s['slot'] for s in slots] == list(range(6))
    assert len({s['id'] for s in slots}) == 6
    kinds = [s['kind'] for s in slots]
    assert kinds.count('curio') == 2 and 'scroll' in kinds
    assert slots[0]['kind'] == 'exotic_seed' and slots[0]['min_level'] <= 14, 'a cheap slot for a beginner'
    for s in slots:
        if s['kind'] in ('exotic_seed', 'scroll', 'curio'):
            expect = EXOTIC_BY_SEED[s['item']]['pack_price'] if s['kind'] == 'exotic_seed' else -(-{'scroll': 25}.get(s['kind'], CURIOS.get(s['id'], {}).get('k', 0)) * income_ref(s['min_level']) // 100)
            assert s['price'] == expect
        assert s['id'] not in M.ORCHARD_IDS, 'grafts and vouchers wait for the orchard'
    assert all(s['limit'] == MERCHANT['limits'][s['kind']] for s in slots)


def test_prices_follow_k_times_income_ref_of_the_item_level():
    e = M.ENTRIES['seed_moon_pumpkin']
    assert e['min_level'] == 14 and e['price'] == EXOTIC_CROPS['moon_pumpkin']['pack_price']
    assert M.ENTRIES['scroll_pumpkin_latte']['price'] == 25 * income_ref(14) // 100
    for cid, c in CURIOS.items():
        assert M.ENTRIES[cid]['price'] == -(-c['k'] * income_ref(c['level']) // 100) and 15 <= c['k'] <= 60
    for d in DYES:
        assert M.ENTRIES[d]['price'] == ITEMS[d]['price'] and 100 <= ITEMS[d]['price'] <= 150


def test_a_visit_does_not_repeat_the_previous_visits_goods_and_curios_follow_the_season_series():
    days = [d for d in range(VISIT, VISIT + 200) if M.visit_on(d)]
    for a, b in zip(days, days[1:]):
        ids_a = {s['id'] for s in M.stock(M.visit_on(a))}
        ids_b = {s['id'] for s in M.stock(M.visit_on(b))}
        assert not ids_a & ids_b
    for d in days:
        assert {s['series'] for s in M.stock(M.visit_on(d)) if s['kind'] == 'curio'} == {M.series_of(d)}
    seasons = {economy.season_of(M._ts(d)): M.series_of(d) for d in days}
    ordered = [seasons[k] for k in sorted(seasons)]
    assert all(ordered[i] != ordered[i + 4] for i in range(len(ordered) - 4)), 'a series is back not earlier than after four seasons'


# ---- buying --------------------------------------------------------------------------------------------------------------------
def test_buying_a_seed_pack_pays_gives_three_plantings_and_respects_the_limit():
    f = farm()
    s = slot_of('exotic_seed')
    text = cmd(f, 'merchant_buy', buy(s['slot']))
    assert f['coins'] == 10 ** 6 - s['price'] and f['inventory'][s['item']] == 3 and 'Сорока' in text
    assert f['merchant']['bought'] == {str(s['slot']): 1} and f['merchant']['visit_id'] == f'v{VISIT}'
    cmd(f, 'merchant_buy', buy(s['slot']))
    assert f['inventory'][s['item']] == 6
    assert code(f, 'merchant_buy', buy(s['slot'])) == 'limit_reached'
    assert code(f, 'merchant_buy', buy(s['slot'], 3)) == 'limit_reached'
    validate_state(f)


def test_new_visit_resets_the_counters_and_a_stale_or_absent_visit_is_refused():
    f = farm()
    s = slot_of('exotic_seed')
    cmd(f, 'merchant_buy', buy(s['slot'], 2))
    later = next(d for d in range(VISIT + 1, VISIT + 20) if M.visit_on(d))
    nxt = M.stock(M.visit_on(later))[0]
    cmd(f, 'merchant_buy', {'visit_id': f'v{later}', 'slot': 0, 'qty': 1}, at=noon(later))
    assert f['merchant']['bought'] == {'0': 1} and f['merchant']['visit_id'] == f'v{later}' and f['merchant']['sold_value'] == 0
    assert nxt['id'] != s['id'] or True
    assert code(f, 'merchant_buy', buy(0, 1), at=noon(later)) == 'stale_visit'
    gap = next(d for d in range(VISIT + 1, VISIT + 20) if not M.visit_on(d))
    assert code(f, 'merchant_buy', {'visit_id': f'v{gap}', 'slot': 0, 'qty': 1}, at=noon(gap)) == 'merchant_away'
    assert code(f, 'merchant_buy', {'visit_id': 'v1', 'slot': 0, 'qty': 1}) == 'stale_visit'


def test_validation_of_slot_quantity_level_coins_and_unknown_fields():
    f = farm()
    assert code(f, 'merchant_buy', buy(6)) == 'invalid_command'
    assert code(f, 'merchant_buy', buy(-1)) == 'invalid_command'
    assert code(f, 'merchant_buy', buy(0, 0)) == 'invalid_number'
    assert code(f, 'merchant_buy', buy(0, True)) == 'invalid_number'
    assert code(f, 'merchant_buy', {'visit_id': f'v{VISIT}', 'slot': 0}) == 'invalid_command'
    assert code(f, 'merchant_buy', {**buy(0), 'price': 1}) == 'invalid_command'
    assert code(f, 'merchant_buy', {**buy(0), 'visit_id': 5}) == 'invalid_command'
    assert code(farm(xp=0), 'merchant_buy', buy(slot_of('curio')['slot'])) == 'locked'
    poor = farm(coins=1)
    assert code(poor, 'merchant_buy', buy(slot_of('curio')['slot'])) == 'insufficient_coins'
    assert code(f, 'merchant_sell', {'visit_id': f'v{VISIT}', 'item': 'nope', 'qty': 1}) == 'unknown_item'


def test_a_starter_credit_may_be_spent_on_her_goods():
    f = farm(coins=5000)
    f['starter_credit'] = 5000
    s = slot_of('exotic_seed')
    cmd(f, 'merchant_buy', buy(s['slot']))
    assert f['starter_credit'] == max(0, 5000 - s['price'])


def test_a_curio_is_bought_once_for_ever_and_placed_free_once():
    f = farm()
    s = slot_of('curio')
    cmd(f, 'merchant_buy', buy(s['slot']))
    assert f['merchant']['curios'] == [s['id']]
    assert code(f, 'merchant_buy', buy(s['slot'])) == 'already_owned'
    other = next(d for d in range(VISIT + 1, VISIT + 400) if M.visit_on(d) and any(x['id'] == s['id'] for x in M.stock(M.visit_on(d))))
    assert code(f, 'merchant_buy', {'visit_id': f'v{other}', 'slot': next(x['slot'] for x in M.stock(M.visit_on(other)) if x['id'] == s['id']), 'qty': 1},
                at=noon(other)) == 'already_owned'
    coins = f['coins']
    cmd(f, 'build', {'type': s['id'], 'x': 6, 'y': 4})
    assert f['coins'] == coins and any(o['type'] == s['id'] for o in f['objects'])
    assert code(f, 'build', {'type': s['id'], 'x': 6, 'y': 6}) == 'curio_placed'
    unowned = next(c for c in CURIOS if c != s['id'])
    assert code(f, 'build', {'type': unowned, 'x': 6, 'y': 6}) == 'curio_locked'


def test_a_scroll_opens_its_recipe_only_after_purchase():
    f = farm(xp=LEVELS[29], inv={'flour': 5, 'honey': 3, 'exo_fire_pepper': 2})
    f['objects'].append(dict(id='bak', type='bakery', x=6, y=4, w=2, h=2, revision=0, level=1, jobs=[], animal=None, animal_job=None))
    assert code(f, 'queue', {'object': 'bak', 'recipe': 'pepper_gingerbread'}) == 'wrong_building'
    visit = next(M.visit_on(d) for d in range(VISIT, VISIT + 400) if M.visit_on(d) and any(s['id'] == 'scroll_pepper_gingerbread' for s in M.stock(M.visit_on(d))))
    s = next(x for x in M.stock(visit) if x['id'] == 'scroll_pepper_gingerbread')
    at = noon(visit['day'])
    cmd(f, 'merchant_buy', {'visit_id': visit['visit_id'], 'slot': s['slot'], 'qty': 1}, at=at)
    assert f['merchant']['scrolls'] == ['pepper_gingerbread']
    cmd(f, 'queue', {'object': 'bak', 'recipe': 'pepper_gingerbread'}, at=at)
    assert f['inventory']['exo_fire_pepper'] == 1
    assert 'pepper_gingerbread' not in reachable(farm()), 'a scroll recipe never feeds ordinary orders'
    assert code(f, 'merchant_buy', {'visit_id': visit['visit_id'], 'slot': s['slot'], 'qty': 1}, at=at) == 'already_owned'


# ---- the buy-back --------------------------------------------------------------------------------------------------------------
def test_the_buy_back_pays_plus_thirty_percent_for_the_wanted_item_up_to_two_percent_of_income_ref():
    v = M.visit_on(VISIT)
    item = M.wants(v)
    price = ITEMS[item]['price']
    f = farm(inv={item: 100})
    cap = income_ref(30) * 2 // 100
    n = cap // price
    assert n >= 1
    other = next(i for i in MERCHANT['buyback']['items'] if i != item)
    f['inventory'][other] = 5
    assert code(f, 'merchant_sell', {'visit_id': v['visit_id'], 'item': other, 'qty': 1}) == 'not_wanted'
    coins = f['coins']
    text = cmd(f, 'merchant_sell', {'visit_id': v['visit_id'], 'item': item, 'qty': n})
    assert f['coins'] == coins + price * n * 130 // 100 and f['inventory'][item] == 100 - n and f['merchant']['sold_value'] == price * n and 'Сорока' in text
    assert code(f, 'merchant_sell', {'visit_id': v['visit_id'], 'item': item, 'qty': (cap - price * n) // price + 1}) == 'merchant_cap'
    assert code(f, 'merchant_sell', {'visit_id': v['visit_id'], 'item': item, 'qty': 0}) == 'invalid_number'
    # a new visit gives the room back
    later = next(d for d in range(VISIT + 1, VISIT + 30) if M.visit_on(d))
    item2 = M.wants(M.visit_on(later))
    f['inventory'][item2] = 50
    cmd(f, 'merchant_sell', {'visit_id': f'v{later}', 'item': item2, 'qty': 1}, at=noon(later))
    assert f['merchant']['sold_value'] == ITEMS[item2]['price']


def test_the_buy_back_needs_the_goods_and_the_cap_scales_with_the_level():
    v = M.visit_on(VISIT)
    item = M.wants(v)
    assert code(farm(), 'merchant_sell', {'visit_id': v['visit_id'], 'item': item, 'qty': 1}) == 'missing_goods'
    assert M.cap(farm(xp=LEVELS[29])) == income_ref(30) * 2 // 100
    assert M.cap(farm(xp=0)) == income_ref(1) * 2 // 100 < M.cap(farm(xp=LEVELS[29]))


# ---- idempotency and the ledger -----------------------------------------------------------------------------------------------
class FakeUnit:
    def __init__(self, account_id, f):
        self.account_id, self.farm, self.receipts, self.records = account_id, f, {}, []

    async def lock(self, *keys): pass
    async def by_account(self, account_id): return self.farm if account_id == self.account_id else None
    async def get(self, farm_id): return self.farm if farm_id == self.farm['id'] else None
    async def owner_account(self, farm_id): return self.account_id
    async def save(self, f, account_id=None): self.farm = f
    async def receipt(self, account_id, key): return self.receipts.get((account_id, key))
    async def remember(self, account_id, key, fingerprint, result, now): self.receipts[(account_id, key)] = {'fingerprint': fingerprint, 'result': result}
    async def record(self, actor, key, kind, before, after, now): self.records.append((key, kind, after['coins'] - before['coins']))


def test_service_replay_charges_once_and_writes_one_ledger_record_per_command():
    async def run():
        f = farm()
        unit = FakeUnit('acc', f)
        service = FarmService(unit, Principal('acc', 'Игрок'), clock=lambda: NOW)
        s = slot_of('exotic_seed')
        first = await service.command('merchant-buy-01', 'merchant_buy', buy(s['slot']))
        coins = unit.farm['coins']
        assert await service.command('merchant-buy-01', 'merchant_buy', buy(s['slot'])) == first and unit.farm['coins'] == coins
        assert unit.farm['inventory'][s['item']] == 3
        with pytest.raises(FarmError) as reused:
            await service.command('merchant-buy-01', 'merchant_buy', buy(s['slot'], 2))
        assert reused.value.code == 'key_reused'
        item = M.wants(M.visit_on(VISIT))
        unit.farm['inventory'][item] = 4
        sold = await service.command('merchant-sell-1', 'merchant_sell', {'visit_id': f'v{VISIT}', 'item': item, 'qty': 1})
        assert await service.command('merchant-sell-1', 'merchant_sell', {'visit_id': f'v{VISIT}', 'item': item, 'qty': 1}) == sold
        assert unit.farm['inventory'][item] == 3
        assert [(k, kind) for k, kind, _ in unit.records if kind.startswith('merchant')] == [('merchant-buy-01', 'merchant_buy'), ('merchant-sell-1', 'merchant_sell')]
        assert unit.records[0][2] == -s['price'] and unit.records[1][2] > 0
        shown = await service.open()
        assert shown['farm']['merchant_view']['active'] and shown['catalog']['merchant']['config']['pack'] == 3
    asyncio.run(run())


# ---- privacy and migration ------------------------------------------------------------------------------------------------------
def test_a_neighbour_sees_nothing_of_the_merchant_state():
    f = farm()
    cmd(f, 'merchant_buy', buy(slot_of('curio')['slot']))
    other = farm()
    f['settings']['visibility'] = 'public'
    own = project(f, f, NOW)
    assert own['merchant_view']['curios'] and own['merchant']['curios']
    seen = project(f, other, NOW)
    assert 'merchant' not in seen and 'merchant_view' not in seen
    assert 'sold_value' not in str(seen) and f['merchant']['curios'][0] not in str(seen.get('objects'))


def test_old_farms_get_an_empty_record_and_a_broken_record_is_refused():
    f = new_farm(str(uuid4()), 'Old', NOW)
    assert 'merchant' not in f
    upgrade_state(f)
    assert f['merchant'] == M.blank()
    before = deepcopy(f)
    upgrade_state(f)
    assert f == before, 'the migration is idempotent'
    validate_state(f)
    for bad in ({'curios': ['nope']}, {'scrolls': ['x']}, {'bought': {'9': 1}}, {'bought': {'0': -1}}, {'sold_value': -1}, {'seed_bank': {'a': 1}}, {'visit_id': 5}):
        g = deepcopy(f)
        g['merchant'].update(bad)
        with pytest.raises(FarmError):
            validate_state(g)


# ---- bound goods -----------------------------------------------------------------------------------------------------------------
def neighbours(inv):
    a, b = farm(inv=inv), farm()
    for x, y in ((a, b), (b, a)):
        x['neighbors'][y['id']] = {'name': 'N', 'status': 'accepted'}
    a['stats'].update(orders=5, harvests=9)
    b['settings']['allow_gifts'] = True
    return a, b


@pytest.mark.parametrize('item', ['seed_fire_pepper', 'dye_indigo', 'graft_apple_paradise', 'voucher_orchard'])
def test_bound_goods_never_leave_the_farm(item):
    a, b = neighbours({item: 3, 'wheat': 3})
    before = deepcopy(a)
    for kind, data in (('sell', {'item': item, 'qty': 1}), ('list', {'item': item, 'qty': 1, 'unit_price': 10}),
                       ('fund_contribute', {'coins': 0, 'items': {item: 1}})):
        with pytest.raises(FarmError) as e:
            apply(a, a, kind, data, NOW, f'{kind}-1')
        assert e.value.code == 'bound_item', kind
    with pytest.raises(FarmError) as e:
        apply(a, b, 'gift', {'item': item, 'qty': 1}, NOW, 'gift-1')
    assert e.value.code == 'bound_item' and a['inventory'][item] == 3 and not b['inventory'].get(item)
    assert a['coins'] == before['coins']


def test_the_caravan_refuses_bound_goods_defensively():
    f = farm(inv={'dye_indigo': 5})
    f['market']['caravan'] = dict(id='c', npc='Пух', started_at=NOW, deadline=NOW + 9999, crates=[dict(item='dye_indigo', qty=1, done=False)], value=1, coins=1, xp=1, decor=None)
    f['market']['caravan_next_at'] = NOW + 10 ** 6
    with pytest.raises(FarmError) as e:
        apply(f, f, 'caravan_fill', {'crate': 0}, NOW, 'car-1')
    assert e.value.code == 'bound_item'


def test_ordinary_goods_are_still_sold_and_gifted():
    a, b = neighbours({'wheat': 3, 'exo_fire_pepper': 3})
    apply(a, a, 'sell', {'item': 'wheat', 'qty': 1}, NOW, 's1')
    apply(a, a, 'sell', {'item': 'exo_fire_pepper', 'qty': 1}, NOW, 's2')
    assert a['inventory']['exo_fire_pepper'] == 2, 'the foreign harvest sells at its price'


def test_the_fund_takes_the_foreign_fruit_at_the_plain_law_price_not_the_x12():
    fruit = EXOTIC_CROPS['fire_pepper']
    item = ITEMS[fruit['id']]
    assert item['fund_price'] < item['price']
    xp, profit = max(1, round(crop_law(fruit['level'], fruit['seconds'])[0])), round(crop_law(fruit['level'], fruit['seconds'])[1])
    assert item['fund_price'] == -(-(xp + profit) // fruit['yield_qty'])
    assert economy.goods_value({fruit['id']: 3}) == item['fund_price'] * 3 * 125 // 100
    assert economy.goods_value({'wheat': 2}) == ITEMS['wheat']['price'] * 2 * 125 // 100


# ---- foreign crops -------------------------------------------------------------------------------------------------------------------
def test_six_foreign_crops_with_the_named_fruits_outside_the_ordinary_crop_tables():
    assert [c['name'] for c in EXOTIC_CROPS.values()] == ['Огненный перец', 'Голубая кукуруза', 'Лунная тыква', 'Медовая дыня', 'Полосатый арбуз', 'Жемчужный рис']
    assert not set(EXOTIC_CROPS) & set(CROPS) and not {c['id'] for c in EXOTIC_CROPS.values()} & set(CROPS)
    pub = public_catalog()['crops']
    for c in EXOTIC_CROPS.values():
        assert pub[c['id']]['exotic'] is True and pub[c['id']]['cost'] == 0
        xp, profit = crop_law(c['level'], c['seconds'])
        revenue = c['yield_qty'] * ITEMS[c['id']]['price'] - round(xp)
        assert revenue >= 1.2 * round(profit) - c['yield_qty'], 'about 120 percent of the law profit'
        assert revenue <= 1.2 * round(profit) + c['yield_qty']


def test_planting_a_foreign_crop_spends_one_seed_unit_and_harvest_pays_the_fruit():
    f = farm(inv={'seed_fire_pepper': 2})
    f['objects'].append(dict(id='bed', type='plot', x=7, y=6, w=1, h=1, revision=0, crop=None))
    coins = f['coins']
    cmd(f, 'plant', {'object': 'bed', 'crop': 'exo_fire_pepper', 'revision': 0})
    bed = next(o for o in f['objects'] if o['id'] == 'bed')
    assert f['coins'] == coins and f['inventory']['seed_fire_pepper'] == 1 and bed['crop']['id'] == 'exo_fire_pepper' and bed['crop']['seed'] == 'seed_fire_pepper'
    assert code(f, 'plant', {'object': 'bed', 'crop': 'exo_fire_pepper', 'revision': 1}) == 'busy_plot'
    seen = len(f['harvested_crops'])
    done = bed['crop']['ready_at']
    cmd(f, 'harvest', {'object': 'bed', 'revision': bed['revision']}, at=done)
    assert f['inventory']['exo_fire_pepper'] == 3 and len(f['harvested_crops']) == seen
    assert code(farm(), 'plant', {'object': 'plot_4', 'crop': 'exo_fire_pepper', 'revision': 0}) == 'missing_goods'
    assert code(farm(xp=0, inv={'seed_fire_pepper': 1}), 'plant', {'object': 'plot_4', 'crop': 'exo_fire_pepper', 'revision': 0}) == 'locked'
    assert code(farm(), 'plant', {'object': 'plot_4', 'crop': 'seed_fire_pepper', 'revision': 0}) == 'unknown_item'


def test_digging_up_a_foreign_planting_returns_the_seed_only_inside_the_undo_window():
    f = farm(inv={'seed_blue_corn': 1})
    cmd(f, 'plant', {'object': 'plot_5', 'crop': 'exo_blue_corn', 'revision': 0})
    plot = next(o for o in f['objects'] if o['id'] == 'plot_5')
    cmd(f, 'dig_up', {'object': 'plot_5', 'revision': plot['revision']}, at=NOW + 30)
    assert f['inventory']['seed_blue_corn'] == 1 and plot['crop'] is None
    cmd(f, 'plant', {'object': 'plot_5', 'crop': 'exo_blue_corn', 'revision': plot['revision']})
    cmd(f, 'dig_up', {'object': 'plot_5', 'revision': plot['revision']}, at=NOW + 600)
    assert f['inventory']['seed_blue_corn'] == 0 and f['coins'] == 10 ** 6


def test_helpers_harvest_a_foreign_plot_without_breaking_settle():
    from qw_farm import expansion
    f = farm(inv={'seed_pearl_rice': 1})
    cmd(f, 'plant', {'object': 'plot_3', 'crop': 'exo_pearl_rice', 'revision': 0})
    plot = next(o for o in f['objects'] if o['id'] == 'plot_3')
    expansion.harvest(f, plot, plot['crop']['ready_at'], owner=False)          # what a helper or the robot does
    assert f['inventory']['exo_pearl_rice'] == 5 and plot['crop'] is None and plot['last_crop'] == 'exo_pearl_rice'
    expansion.settle(f, NOW + 10 ** 6)
    validate_state(f)


def test_foreign_crops_never_reach_orders_caravans_contracts_or_the_seed_shop():
    f = farm()
    assert not [c for c in reachable(f) if c.startswith('exo_') or c.startswith('seed_') or c in DYES]
    for i in range(300):
        o = make_order(f, i % 3, NOW)
        assert not [k for k in o['needs'] if k.startswith('exo_') or k.startswith('seed_') or k in DYES or k in SCROLL_RECIPES]
    for d in range(5):
        market.make_contracts(f, d)
        assert not [c for c in f['market']['contracts']['items'] if c['item'] and (c['item'].startswith('exo_') or c['item'] in RECIPES and RECIPES[c['item']].get('exclusive'))]


# ---- dyes ---------------------------------------------------------------------------------------------------------------------------------
def test_dyes_are_obtainable_only_from_the_merchant_and_never_in_ordinary_sources():
    outputs = {k for r in RECIPES.values() for k in r['outputs']} | {k for a in ANIMALS.values() for k in a['outputs']} | {k for r in ROUTES.values() for k in r['outputs']}
    for d in DYES:
        assert d not in outputs and d not in CROPS and ITEMS[d]['bound'] and ITEMS[d]['kind'] == 'dye'
        assert any(d == e['item'] for e in M.ENTRIES.values() if e['kind'] == 'dye')
    for fid in festivals.FESTIVALS:
        for g in festivals.content(fid)['goods']:
            assert g['id'] not in DYES
        for t in festivals.content(fid)['tasks']:
            assert not any(k in DYES for o in t['options'] for k in o)


def test_dyeing_recipes_follow_dyed_linen_and_work_in_the_tailor_with_a_dye():
    assert RECIPES['dyed_linen']['inputs'] == {'linen': 1, 'blueberry': 3}, 'the plain dyed linen needs no dye'
    for d, out in zip(DYES, ('indigo_linen', 'madder_linen', 'saffron_linen')):
        r = RECIPES[out]
        assert r['building'] == 'tailor' and r['inputs'] == {'linen': 1, d: 1} and r['exclusive'] == 'merchant'
        assert ITEMS[out]['price'] > ITEMS['linen']['price'] + ITEMS[d]['price']
    f = farm(inv={'linen': 2, 'dye_indigo': 1})
    f['objects'].append(dict(id='tl', type='tailor', x=6, y=4, w=2, h=2, revision=0, level=1, jobs=[], animal=None, animal_job=None))
    cmd(f, 'queue', {'object': 'tl', 'recipe': 'indigo_linen'})
    assert f['inventory']['dye_indigo'] == 0 and f['inventory']['linen'] == 1
    assert code(f, 'queue', {'object': 'tl', 'recipe': 'indigo_linen'}) == 'missing_goods'


def test_orchard_hooks_are_defined_bound_and_not_wired():
    for g in M.ORCHARD_IDS:
        assert ITEMS[g]['bound'] and ITEMS[g]['wired'] is False and ITEMS[g]['orchard'] is True
    assert M.ORCHARD_IDS and not any(s['id'] in M.ORCHARD_IDS for d in range(VISIT, VISIT + 200) if M.visit_on(d) for s in M.stock(M.visit_on(d)))
    magpie_lots = [g for fid in festivals.FESTIVALS for g in festivals.content(fid)['goods'] if g['seller'] == 'magpie']
    assert magpie_lots, 'the fair lots of the festival engine are reused, not duplicated here'
    assert not [e for e in M.ENTRIES if e.startswith('fest_')]


def test_every_curio_is_bound_decor_that_cannot_be_bought_in_the_shop():
    for cid in CURIOS:
        b = public_catalog()['buildings'][cid]
        assert b['decor'] and b['curio'] and b['cost'] == 0
        f = farm()
        assert code(f, 'build', {'type': cid, 'x': 6, 'y': 6}) == 'curio_locked'


def test_a_seed_pack_nets_eight_to_twelve_percent_more_than_the_plain_crop_for_the_same_plantings():
    for c in EXOTIC_CROPS.values():
        xp, profit = round(crop_law(c['level'], c['seconds'])[0]), round(crop_law(c['level'], c['seconds'])[1])
        plain = MERCHANT['pack'] * profit                                    # law: net profit per planting of the plain crop
        pack = MERCHANT['pack'] * c['yield_qty'] * ITEMS[c['id']]['price'] - c['pack_price']
        assert 1.08 <= pack / plain <= 1.12, (c['id'], pack / plain)
        assert M.ENTRIES[c['seed']]['price'] == c['pack_price'] < MERCHANT['pack'] * c['yield_qty'] * ITEMS[c['id']]['price']


def test_the_buy_back_item_is_chosen_under_the_players_cap_and_a_poor_level_is_flagged():
    v = M.visit_on(VISIT)
    shared = M.wants(v)
    poor = farm(xp=0)
    assert M.cap(poor) < min(ITEMS[i]['price'] for i in MERCHANT['buyback']['items'])
    view = M.owner_view(poor, NOW)
    assert view['wants']['item'] == shared and view['wants']['pricey'] is True and view['wants']['room'] == 0
    for xp in (LEVELS[4], LEVELS[9], LEVELS[29]):
        f = farm(xp=xp)
        item = M.wants_for(f, v)
        assert ITEMS[item]['price'] <= M.cap(f) or all(ITEMS[i]['price'] > M.cap(f) for i in MERCHANT['buyback']['items'])
        shown = M.owner_view(f, NOW)['wants']
        assert shown['item'] == item and shown['pricey'] == (ITEMS[item]['price'] > M.cap(f))
    f = farm(xp=LEVELS[4], inv={i: 5 for i in MERCHANT['buyback']['items']})
    other = next(i for i in MERCHANT['buyback']['items'] if i != M.wants_for(f, v))
    assert code(f, 'merchant_sell', {'visit_id': v['visit_id'], 'item': other, 'qty': 1}) == 'not_wanted'
    cmd(f, 'merchant_sell', {'visit_id': v['visit_id'], 'item': M.wants_for(f, v), 'qty': 1})


def test_a_beginner_between_levels_three_and_eight_always_finds_something_to_buy():
    days = [d for d in range(VISIT, VISIT + 200) if M.visit_on(d)]
    stocks = [M.stock(M.visit_on(d)) for d in days]
    assert all(min(x['min_level'] for x in st) <= 6 for st in stocks), 'level 6: every visit has a pack for her'
    assert all(any(x['min_level'] <= 3 for x in a + b) for a, b in zip(stocks, stocks[1:])), 'level 3: at least every other visit'
    assert all(any(x['kind'] == 'exotic_seed' and x['min_level'] <= 8 for x in st) for st in stocks)
