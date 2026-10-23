"""Owner-approved economy audit: progressive rent, sandbox workshop law and shared reference."""
from copy import deepcopy

import pytest

from qw_farm import catalog as C, economy as E, festivals as F, market as M, merchant
from qw_farm.domain import new_farm
from qw_farm.expansion import upgrade_state


@pytest.mark.parametrize('size,count,expected,next_rent', [
    (20, 7, 210, 55), (20, 8, 265, 80), (30, 17, 17 * C.plot_upkeep(30), C.plot_upkeep(30) + 25),
])
def test_progressive_tree_rent_counts_only_trees_and_land_allowance(size, count, expected, next_rent):
    farm = dict(size=size, objects=[dict(id=f't{i}', type='tree', planted_at=100 - i) for i in range(count)])
    before = deepcopy(farm)
    assert E.tree_upkeep(farm) == E.base_upkeep(farm) == expected
    assert E.tree_rent(size, count + 1) == next_rent
    assert farm == before
    farm['objects'].insert(0, dict(id='p', type='plot'))
    assert E.base_upkeep(farm) == expected + C.plot_upkeep(size)


def test_tree_order_survives_object_reordering_and_legacy_timestamps():
    farm = dict(size=20, objects=[dict(id='c', type='tree', planted_at=10), dict(id='a', type='tree'),
                                 dict(id='b', type='tree', planted_at=10)])
    assert [o['id'] for o in E.ordered_trees(farm)] == ['a', 'b', 'c']
    farm['objects'].reverse()
    assert [o['id'] for o in E.ordered_trees(farm)] == ['a', 'b', 'c']


@pytest.mark.parametrize('recipe,price,xp', [
    ('apricot_five_star', 1254, 90), ('cherry_tincture', 378, 63), ('plum_liqueur', 359, 63),
    ('rejuvenating_elixir', 1317, 63), ('pear_sparkle', 377, 55), ('cellar_chest', 1597, 45),
])
def test_long_sandbox_recipes_follow_sqrt_time_and_downstream_inputs(recipe, price, xp):
    assert C.ITEMS[recipe]['price'] == price
    assert C.RECIPES[recipe]['xp'] == xp


def test_workshop_hour_boundary_and_legacy_recipes_keep_their_law():
    assert C.RECIPES['cider_zero']['xp'] == 45
    assert C.ITEMS['cider_zero']['price'] == 275
    assert C.RECIPES['dried_apples']['xp'] == 22
    assert C.ITEMS['dried_apples']['price'] == 164
    # The changed XP law belongs to the new cellar; older workshops retain their original rule.
    assert C._xp_r9('creamery', 7200) == 90
    assert C._xp_r9('bakery', 7200) == 80


def test_voucher_is_affordable_at_merchant_and_every_festival():
    assert C.MERCHANT['orchard_k']['voucher_orchard'] == 2
    assert merchant.ENTRIES['voucher_orchard']['price'] == 380
    assert C.TREE_VOUCHER_DISCOUNT_PCT == 25
    vouchers = [good for content in F.CONTENT.values() if content for good in content['goods'] if good['kind'] == 'voucher']
    assert len(vouchers) == 3 and all(good['k'] == 2 for good in vouchers)
    assert all(F.price(good) == C.income_ref(good['level']) * 2 // 100 for good in vouchers)


def test_income_reference_recalibrates_late_bands_and_drives_caravan_and_fund():
    assert [C.income_ref(lv) for lv in (16, 20, 25, 30, 35, 40, 45, 50)] == [
        19000, 46000, 64000, 76000, 83000, 87000, 89000, 89000]
    for lv in range(10, 51):
        ref = C.income_ref(lv)
        assert M.caravan_target(lv) == round(ref * .08)
        assert M.max_extra_daily(lv)['reference'] == ref
        assert M.max_extra_daily(lv)['share'] <= .25
    assert E.thresholds(C.income_ref(30)) == [38000, 114000, 228000, 380000, 608000]


def test_old_saves_keep_balances_inventory_and_queued_job_rewards_on_repeated_load():
    farm = upgrade_state(new_farm('audit-legacy', 'Farm', 1_800_000_000))
    mill = next(o for o in farm['objects'] if o['type'] == 'mill')
    # Snapshot from a recipe queued before the law changed: its XP and outputs belong to that job.
    mill['jobs'] = [dict(id='old-job', recipe='apricot_five_star', queued_at=1_800_000_000,
                         ready_at=1_800_014_400, seconds=14400, inputs={'dried_apricot': 2, 'honey': 1},
                         outputs={'apricot_five_star': 1}, xp=180, version=C.VERSION)]
    farm['inventory'] = {'apricot_five_star': 7, 'voucher_orchard': 2, 'egg': 4}
    before = deepcopy((farm['coins'], farm['inventory'], mill['jobs']))
    upgrade_state(farm)
    upgrade_state(farm)
    assert (farm['coins'], farm['inventory'], mill['jobs']) == before


@pytest.mark.parametrize('legacy', [True, False])
def test_caravan_price_migration_preserves_partial_refunds_once(legacy):
    at = 1_800_000_000
    farm = upgrade_state(new_farm('audit-caravan', 'Farm', at))
    farm.update(xp=C.LEVELS[39], starter_credit=0)
    prices = {'apricot_five_star': 2010, 'cellar_chest': 1784, 'wheat': C.ITEMS['wheat']['price']} if legacy else {
        item: C.ITEMS[item]['price'] for item in ('apricot_five_star', 'cellar_chest', 'wheat')}
    crates = [dict(item='apricot_five_star', qty=2, done=True), dict(item='cellar_chest', qty=1, done=True),
              dict(item='wheat', qty=4, done=False)]
    car = dict(id='old-caravan', npc=C.NPCS[0][0], started_at=at, deadline=at + 10, crates=crates,
               value=sum(prices[c['item']] * c['qty'] for c in crates), coins=10000, xp=10, decor=None)
    farm['market']['caravan'] = car
    before = deepcopy((farm['coins'], farm['inventory']))
    upgrade_state(farm)
    upgrade_state(farm)
    assert (farm['coins'], farm['inventory']) == before
    assert [c['unit_price'] for c in crates] == [prices[c['item']] for c in crates]
    M.settle_caravan(farm, at + 10)
    expected = prices['apricot_five_star'] * 2 + prices['cellar_chest']
    assert farm['coins'] == before[0] + expected
    assert farm['inventory'] == before[1]
    assert farm['market']['last_caravan']['refund'] == expected
    M.settle_caravan(farm, at + 11)
    assert farm['coins'] == before[0] + expected and farm['market']['caravans_failed'] == 1


def test_new_caravans_snapshot_prices_and_preserve_them_after_catalog_changes(monkeypatch):
    at = 1_800_000_000
    farm = upgrade_state(new_farm('audit-new-caravan', 'Farm', at))
    farm.update(xp=C.LEVELS[39], starter_credit=0)
    monkeypatch.setattr(M, 'reachable_items', lambda _: ['apricot_five_star', 'cellar_chest', 'wheat'])
    M.make_caravan(farm, at)
    car = farm['market']['caravan']
    crate = next(c for c in car['crates'] if c['item'] == 'apricot_five_star')
    crate['done'] = True
    expected = crate['unit_price'] * crate['qty']
    before = farm['coins']
    monkeypatch.setitem(C.ITEMS['apricot_five_star'], 'price', 1)
    M.settle_caravan(farm, car['deadline'])
    assert farm['coins'] == before + expected
