"""E27: the economy softening package of 2026-10-29 (docs/tasks/FARM_ECONOMY_SOFTENING.md, owner decision in section 6).

F1/F2/F3 fields, F4 undo of a sowing, B1/B2/B3 buildings, L1 land, D1/D2 refunds, V1/V4 traps, and old saves (priced or saved by the
previous constants) that must still pass ``validate_state``."""
import math
from copy import deepcopy
from uuid import uuid4

import pytest

from qw_farm import catalog, economy, fields, merchant, undo
from qw_farm.catalog import (ANIMALS, BUILDINGS, CROPS, FIELD_FUEL, FIELD_MACHINES, FIELD_SEED_MULT, FIELD_STEPS, FIELD_UPKEEP, LAND_STEPS,
                             LEVELS, UPGRADES, income_ref, upgrade_cost)
from qw_farm.domain import FarmError, apply, new_farm, project, validate_state
from qw_farm.expansion import settle, upgrade_state

T0 = 1_800_000_000
DAY = 86400


def farm(lv=30, coins=10 ** 8, credit=0, size=20):
    f = upgrade_state(new_farm(str(uuid4()), 'Soft', T0))
    f.update(xp=LEVELS[lv - 1] + 3, coins=coins, starter_credit=credit, size=size)
    f['progress'].update(day=10 ** 9, dew=10 ** 9, last=10 ** 9, pool=0)      # exact XP: no Morning dew, no vigour
    economy.state(f)['billed_day'] = 10 ** 9                                     # no upkeep bill in the middle of a test
    return f


def cmd(f, kind, data=None, at=T0):
    return apply(f, f, kind, data if data is not None else {}, at, str(uuid4()))


def fail(f, kind, data, at=T0, code=None):
    before = deepcopy(f)
    with pytest.raises(FarmError) as error:
        cmd(f, kind, data, at)
    if code:
        assert error.value.code == code
    assert f == before, 'a refused command leaves the farm untouched'


def put(f, kind, oid='target', level=1, **extra):
    obj = dict(id=oid, type=kind, x=3, y=6, w=2, h=2, revision=0, level=level, jobs=[], animal=None, animal_job=None)
    obj.update(extra)
    f['objects'].append(obj)
    return obj


def free_cell(f, w=2, h=2):
    for y in range(0, f['size'] - h + 1):
        for x in range(0, f['size'] - w + 1):
            if not any(o['x'] < x + w and x < o['x'] + o['w'] and o['y'] < y + h and y < o['y'] + o['h'] for o in f['objects']):
                return x, y
    raise AssertionError('no free place')


# ------------------------------------------------------------------------------------------------------------------ F1 / F2 / F3
def test_field_upkeep_is_1000_and_the_step_prices_are_unchanged():
    assert FIELD_UPKEEP == 1000 and catalog.field_catalog()['upkeep'] == 1000
    assert [s['cost'] for s in FIELD_STEPS] == [60000, 120000, 250000, 450000, 800000]          # F3: not touched
    f = farm(44)
    base = economy.base_upkeep(f)
    for step in range(5):
        cmd(f, 'buy_field', dict(step=step))
    assert economy.base_upkeep(f) == base + 1000 * 9
    from qw_farm.upkeep_config import defaults, settings_for
    assert defaults()['field_per_hectare'] == 1000
    assert economy.base_upkeep(f, {'field_per_hectare': 1500}) == base + 1500 * 9           # a stored admin config keeps its number


def test_machine_width_upgrades_cost_15k_and_45k():
    assert all(m['costs'][1:] == (15000, 45000) for m in FIELD_MACHINES.values())
    assert [m['costs'][0] for m in FIELD_MACHINES.values()] == [5000, 7500, 12500, 7000]         # the first rank is unchanged
    f = farm(44)
    cmd(f, 'buy_machine', dict(machine='seeder'))
    for price in (15000, 45000):
        before = f['coins']
        cmd(f, 'upgrade_machine', dict(machine='seeder'))
        assert before - f['coins'] == price


# ------------------------------------------------------------------------------------------------------------------ B1 / B2 / B3
@pytest.mark.parametrize('kind', ['mill', 'noodle_shop', 'pheasantry', 'cellar'])
def test_building_upkeep_follows_the_base_price_not_the_level(kind):
    f = farm(30)
    f['objects'] = []
    spec = BUILDINGS[kind]
    put(f, kind, level=1)
    one = economy.base_upkeep(f)
    assert one == math.ceil(spec['cost'] / 100)
    f['objects'][0]['level'] = 3
    assert economy.base_upkeep(f) == one                                        # an upgrade adds nothing to the bill
    f['objects'][0]['level'] = 'x'                                              # damaged data is not an error either
    assert economy.base_upkeep(f) == one


def test_upgrading_the_dearest_workshop_is_no_longer_a_loss_by_upkeep():
    f = farm(50)
    f['objects'] = []
    put(f, 'noodle_shop')
    before = economy.base_upkeep(f)
    f['starter_credit'] = 0
    f['inventory'].update(UPGRADES[2]['items'])
    cmd(f, 'upgrade', dict(object='target', revision=0))
    assert f['objects'][0]['level'] == 2 and economy.base_upkeep(f) == before == 180


def test_late_buildings_have_the_softened_prices():
    assert {k: BUILDINGS[k]['cost'] for k in ('noodle_shop', 'pheasantry', 'soapery', 'yak_pen', 'silk_house', 'ostrich_farm', 'syrupery',
                                              'sausage_shop', 'creamery', 'cattle_barn')} == {
        'noodle_shop': 18000, 'pheasantry': 20000, 'soapery': 14000, 'yak_pen': 14000, 'silk_house': 10000, 'ostrich_farm': 7000,
        'syrupery': 10000, 'sausage_shop': 7000, 'creamery': 4500, 'cattle_barn': 4000}
    assert [ANIMALS[k]['cost'] for k in ('ostrich', 'silkworm', 'yak', 'pheasant', 'calf')] == [3000, 4500, 7000, 10000, 2600]
    catalog.validate()
    catalog.validate_economy()


def test_compost_heap_catalog_offers_only_the_economic_upgrade():
    pub = catalog.public_catalog()
    assert pub['upgrades']['kinds']['compost_heap'] == 'compost'
    assert pub['upgrades']['costs']['compost_heap'] == {'2': upgrade_cost('compost_heap', 2), '3': None}
    for rid, inputs in (('compost_grass', {'manure': 1, 'grass': 4}), ('compost_manure', {'manure': 2})):
        recipe = pub['recipes'][rid]
        assert recipe['upgrade_level'] == 2
        assert recipe['upgrade_inputs'] == inputs


# ------------------------------------------------------------------------------------------------------------------ L1
def test_land_steps_after_26_follow_the_fourth_power_law():
    steps = {s['size']: s for s in LAND_STEPS}
    assert [steps[s]['cost'] for s in (22, 24, 26)] == [44300, 74600, 121000]                        # up to 26x26 the old curve
    assert [steps[s]['cost'] for s in (28, 30, 32, 36, 40, 44)] == [163000, 214000, 278000, 445000, 678000, 992000]
    for size in range(28, 61, 2):
        assert abs(steps[size]['cost'] - 121000 * (size / 26) ** 4) <= 0.005 * steps[size]['cost']
    assert all(b['cost'] > a['cost'] for a, b in zip(LAND_STEPS, LAND_STEPS[1:]))
    assert all(s['level'] == min(len(LEVELS), 18 + 5 * (s['size'] - 20) // 2) for s in LAND_STEPS[6:])      # the level gate is the same


# ------------------------------------------------------------------------------------------------------------------ D1
def test_demolishing_an_old_building_returns_half_of_the_investment_and_the_wood():
    f = farm(30)
    cheap = put(f, 'mill', level=1)                                    # saved before E27: no record of the price
    coins, wood = f['coins'], f['inventory'].get('wood', 0)
    cmd(f, 'demolish', dict(object=cheap['id'], revision=0), T0 + 5)
    assert f['coins'] == coins + 50 and f['inventory']['wood'] == wood + 4
    dear = put(f, 'noodle_shop', level=3)
    coins = f['coins']
    cmd(f, 'demolish', dict(object=dear['id'], revision=0), T0 + 5)
    assert f['coins'] == coins + (18000 + 9000 + 18000) // 2                                         # base + upgrades 2 and 3 (coin part)
    assert f['inventory']['wood'] == wood + 4 + 6


def test_a_fresh_building_is_taken_back_in_full_inside_the_window_and_cannot_be_farmed():
    f = farm(30, credit=100)
    x, y = free_cell(f)
    coins, xp, builds = f['coins'], f['xp'], f['stats']['builds']
    cmd(f, 'build', dict(type='dairy', x=x, y=y), T0)
    obj = f['objects'][-1]
    assert obj['paid'] == 320 and obj['built_at'] == T0 and obj['gift'] == 100 and f['coins'] == coins - 320 and f['starter_credit'] == 0
    assert f['xp'] == xp + 5 and f['stats']['builds'] == builds + 1
    wood = f['inventory'].get('wood', 0)
    text = cmd(f, 'demolish', dict(object=obj['id'], revision=obj['revision']), T0 + undo.UNDO_WINDOW)
    assert f['coins'] == coins and f['starter_credit'] == 100                       # the starter gift is restored, not turned into free coins
    assert (f['xp'], f['stats']['builds']) == (xp, builds) and f['inventory'].get('wood', 0) == wood
    assert obj not in f['objects'] and 'полностью' in text


def test_the_window_refund_never_takes_a_level_back():
    f = farm(30)
    f['xp'] = LEVELS[30]                                               # the very first XP point of level 31
    x, y = free_cell(f)
    cmd(f, 'build', dict(type='dairy', x=x, y=y), T0)
    assert f['xp'] == LEVELS[30] + 5
    obj = f['objects'][-1]
    obj['build_xp'] = 50                                               # more than there is above the floor
    cmd(f, 'demolish', dict(object=obj['id'], revision=obj['revision']), T0 + 1)
    assert f['xp'] == LEVELS[30] and catalog.level(f['xp']) == 31


def test_a_building_cleared_after_the_window_returns_half_wood_and_takes_the_build_xp_back():
    f = farm(30, credit=100)
    x, y = free_cell(f)
    cmd(f, 'build', dict(type='dairy', x=x, y=y), T0)
    obj = f['objects'][-1]
    coins, wood, xp = f['coins'], f['inventory'].get('wood', 0), f['xp']
    cmd(f, 'demolish', dict(object=obj['id'], revision=obj['revision']), T0 + undo.UNDO_WINDOW + 1)
    assert f['coins'] == coins + 160 and f['inventory']['wood'] == wood + 4 and f['xp'] == xp - 5 and f['starter_credit'] == 100


def test_an_upgrade_is_refunded_with_the_building_and_decor_without_a_record_gives_nothing():
    f = farm(30)
    x, y = free_cell(f)
    cmd(f, 'build', dict(type='mill', x=x, y=y), T0)
    obj = f['objects'][-1]
    f['inventory'].update(UPGRADES[2]['items'])
    cmd(f, 'upgrade', dict(object=obj['id'], revision=obj['revision']), T0 + 5)
    coins = f['coins']
    goods = dict(f['inventory'])
    cmd(f, 'demolish', dict(object=obj['id'], revision=obj['revision']), T0 + 10)               # still inside the window: all of it
    assert f['coins'] == coins + 100 + 200
    assert all(f['inventory'].get(k, 0) == goods.get(k, 0) + q for k, q in UPGRADES[2]['items'].items())      # the upgrade goods too


def test_after_the_window_half_of_the_upgrade_goods_come_back_rounded_down():
    f = farm(30)
    mill = put(f, 'mill', 'old_mill', level=3)                                                  # saved before E27: no record, two upgrades
    before = dict(f['inventory'])
    text = cmd(f, 'demolish', dict(object=mill['id'], revision=0), T0 + 5)
    back = {k: f['inventory'].get(k, 0) - before.get(k, 0) for k in ('hay', 'flour', 'cheese', 'linen', 'wood')}
    assert back == {'hay': 2, 'flour': 2, 'cheese': 1, 'linen': 1, 'wood': 6}
    assert 'Вернулась половина' in text
    odd = put(f, 'mill', 'odd_mill', level=2, x=8, y=8)
    odd_before = f['inventory'].get('hay', 0)
    UPGRADES[2]['items']['hay'] = 5                                                              # an odd amount rounds down
    try:
        cmd(f, 'demolish', dict(object=odd['id'], revision=0), T0 + 6)
    finally:
        UPGRADES[2]['items']['hay'] = 4
    assert f['inventory'].get('hay', 0) == odd_before + 2


@pytest.mark.parametrize('kind', ['plot', 'flowerbed', 'bench', 'lantern', 'road'])
def test_decor_and_beds_are_refunded_but_building_and_clearing_gives_no_xp(kind):
    """D1: decor (roads too) and beds give back 100 % in the first minute and 50 % later; the 5 build XP and the build counter are
    taken back on every demolition, so ten cycles of build-and-clear never raise XP."""
    f = farm(30)
    price = 35 if kind == 'plot' else BUILDINGS[kind]['cost']
    xp0, builds0, wood0 = f['xp'], f['stats']['builds'], f['inventory'].get('wood', 0)
    for cycle in range(10):
        x, y = free_cell(f, 1, 1)
        coins = f['coins']
        at = T0 + cycle * 1000
        cmd(f, 'build', dict(type=kind, x=x, y=y), at)
        obj = f['objects'][-1]
        assert obj['paid'] == price and f['coins'] == coins - price and f['xp'] == xp0 + 5
        early = cycle % 2 == 1
        cmd(f, 'demolish', dict(object=obj['id'], revision=obj['revision']), at + (undo.UNDO_WINDOW if early else undo.UNDO_WINDOW + 1))
        assert f['coins'] == coins - (0 if early else price - price // 2)       # all of it in the window, half later
        assert f['xp'] == xp0 and f['stats']['builds'] == builds0              # no XP gained from the cycle
    assert f['inventory'].get('wood', 0) == wood0


def test_a_caravan_gift_decor_and_legacy_objects_are_refunded_by_their_record():
    f = farm(30)
    x, y = free_cell(f, 1, 1)
    cmd(f, 'build', dict(type='bench', x=x, y=y), T0)
    gift = f['objects'][-1]
    gift['paid'] = 0                                                           # what a free (caravan) decor records
    coins = f['coins']
    cmd(f, 'demolish', dict(object=gift['id'], revision=gift['revision']), T0 + 5)
    assert f['coins'] == coins and f['xp'] == LEVELS[29] + 3
    old = put(f, 'bench', 'old_bench', w=1, h=1)                                # built before E27: no record, current catalog price, no XP known
    xp, builds = f['xp'], f['stats']['builds']
    coins = f['coins']
    cmd(f, 'demolish', dict(object=old['id'], revision=0), T0 + 5)
    assert f['coins'] == coins + BUILDINGS['bench']['cost'] // 2 and (f['xp'], f['stats']['builds']) == (xp, builds)
    bed = put(f, 'plot', 'old_bed', w=1, h=1, crop=None)
    coins = f['coins']
    cmd(f, 'demolish', dict(object=bed['id'], revision=0), T0 + 5)
    assert f['coins'] == coins + 17
    start = next(o for o in f['objects'] if o['id'] == 'plot_5')               # the starter beds of new_farm give nothing
    assert undo.is_starter(start)
    coins = f['coins']
    cmd(f, 'demolish', dict(object=start['id'], revision=start['revision']), T0 + 5)
    assert f['coins'] == coins


def test_the_starter_buildings_return_nothing_but_old_bought_ones_do():
    f = farm(30)
    starter = next(o for o in f['objects'] if o['id'] == 'building_2')                          # the mill that new_farm hands out
    assert starter['type'] == 'mill' and 'paid' not in starter and undo.is_starter(starter)
    coins, wood = f['coins'], f['inventory'].get('wood', 0)
    cmd(f, 'demolish', dict(object=starter['id'], revision=starter['revision']), T0 + 5)
    assert f['coins'] == coins and f['inventory']['wood'] == wood + 4                         # wood as before, no coins
    f2 = farm(30)
    mill = next(o for o in f2['objects'] if o['id'] == 'building_2')
    mill['level'] = 2                                                                         # an upgrade put into it is real money
    assert undo.building_invested(mill) == 200
    bought = put(f2, 'mill', 'bought_before_e27')                                             # bought earlier: no record of the price
    assert not undo.is_starter(bought) and undo.building_invested(bought) == 100
    coins = f2['coins']
    cmd(f2, 'demolish', dict(object=bought['id'], revision=0), T0 + 5)
    assert f2['coins'] == coins + 50
    new = put(f2, 'mill', 'building_9', paid=100)                                             # a recorded purchase is never a starter one
    assert not undo.is_starter(new)


def test_a_visitor_never_sees_what_a_building_cost():
    owner, guest = farm(30), farm(30)
    x, y = free_cell(owner)
    cmd(owner, 'build', dict(type='dairy', x=x, y=y), T0)
    owner['settings']['visibility'] = 'public'
    shown = project(owner, guest, T0 + 1)
    built = next(o for o in shown['objects'] if o['id'] == owner['objects'][-1]['id'])
    assert not {'paid', 'built_at', 'gift', 'build_xp'} & set(built)


# ------------------------------------------------------------------------------------------------------------------ D2
def test_uprooting_an_old_tree_returns_half_of_the_sapling_price_but_a_free_one_nothing():
    f = farm(30, coins=10 ** 7)
    f['objects'] = []
    cmd(f, 'plant_tree', dict(species='apple', x=10, y=10, voucher=None), T0)
    tree = f['objects'][0]
    cost, coins = tree['cost'], f['coins']
    assert cost > 0
    cmd(f, 'demolish', dict(object=tree['id'], revision=tree['revision']), T0 + undo.UNDO_WINDOW + 1)
    assert f['coins'] == coins + cost // 2 and f['inventory']['wood'] == 2
    cmd(f, 'plant_tree', dict(species='apple', x=10, y=10, voucher=None), T0 + 1000)
    tree = f['objects'][0]
    tree['cost'], tree['paid_with'] = 0, 'free'
    coins = f['coins']
    cmd(f, 'demolish', dict(object=tree['id'], revision=tree['revision']), T0 + 1000 + undo.UNDO_WINDOW + 1)
    assert f['coins'] == coins


# ------------------------------------------------------------------------------------------------------------------ F4
def equipped(lv=44, credit=0):
    f = farm(lv, credit=credit)
    cmd(f, 'buy_field', dict(step=0))
    for name in FIELD_MACHINES:
        cmd(f, 'buy_machine', dict(machine=name))
    f['starter_credit'] = credit
    return f


def field(f):
    return f['fields'][0]


def run_op(f, op, at, crop=''):
    cmd(f, 'field_start', dict(field=field(f)['id'], op=op, crop=crop, revision=field(f)['revision']), at)
    run = field(f)['run']
    path = fields.reference_path(field(f), run)
    done = at + math.ceil(0.12 * len(path)) + 1
    cmd(f, 'field_finish', dict(field=field(f)['id'], run=run['id'], path=path), done)
    return done


def cancel(f, at, revision=None):
    return cmd(f, 'field_cancel', dict(field=field(f)['id'], revision=field(f)['revision'] if revision is None else revision), at)


SOWING = 'saffron'
PRICE = CROPS[SOWING]['cost'] * FIELD_SEED_MULT + FIELD_FUEL


def test_an_open_sowing_run_is_cancelled_with_everything_back():
    f = equipped()
    t = run_op(f, 'cultivate', T0)
    coins = f['coins']
    cmd(f, 'field_start', dict(field=field(f)['id'], op='sow', crop=SOWING, revision=field(f)['revision']), t + 5)
    assert f['coins'] == coins - PRICE and field(f)['run']['cost'] == CROPS[SOWING]['cost'] * FIELD_SEED_MULT
    text = cancel(f, t + 5 + undo.UNDO_WINDOW)
    assert f['coins'] == coins and field(f)['run'] is None and field(f)['state'] == 'ready' and 'вернулись полностью' in text
    validate_state(f)
    fail(f, 'field_cancel', dict(field=field(f)['id'], revision=field(f)['revision']), t + 6, code='nothing_to_cancel')        # idempotent
    run_op(f, 'sow', t + 100, SOWING)                                                  # the field is usable again
    assert field(f)['state'] == 'growing'


def test_a_sown_field_is_cleared_inside_the_first_minute_and_not_after_it():
    f = equipped(credit=500)
    t = run_op(f, 'cultivate', T0)
    q_cult = field(f)['q_cult']
    coins = f['coins']
    done = run_op(f, 'sow', t + 5, SOWING)
    repair = coins - f['coins'] - PRICE                                  # bumps of a manual run are not given back
    crop = field(f)['crop']
    assert field(f)['state'] == 'growing' and crop['cost'] == PRICE - FIELD_FUEL and crop['fuel'] == FIELD_FUEL and crop['gift'] == 300      # 200 of the 500 went into the cultivator's fuel
    assert f['starter_credit'] == 0
    old_revision = field(f)['revision']
    fail(f, 'field_cancel', dict(field=field(f)['id'], revision=old_revision - 1), done, code='stale_object')
    fail(f, 'field_cancel', dict(field=field(f)['id'], revision=old_revision), done + undo.UNDO_WINDOW + 1, code='undo_expired')
    cancel(f, done + undo.UNDO_WINDOW)
    assert f['coins'] == coins - repair and f['starter_credit'] == 300
    assert field(f)['state'] == 'ready' and field(f)['crop'] is None and field(f)['q_cult'] == q_cult and field(f)['revision'] > old_revision
    assert f['events'][0]['kind'] == 'field_cancel'
    validate_state(f)
    fail(f, 'field_cancel', dict(field=field(f)['id'], revision=field(f)['revision']), done + 1, code='nothing_to_cancel')
    fail(f, 'field_cancel', dict(field=field(f)['id'], revision=field(f)['revision'], extra=1), done + 1, code='invalid_command')


def test_an_autopilot_sowing_run_can_be_cancelled_until_it_finishes():
    f = equipped()
    t = run_op(f, 'cultivate', T0)
    coins = f['coins']
    cmd(f, 'field_start', dict(field=field(f)['id'], op='sow', crop=SOWING, revision=field(f)['revision']), t + 5)
    cmd(f, 'field_finish', dict(field=field(f)['id'], run=field(f)['run']['id'], path=None), t + 6)
    assert field(f)['run']['status'] == 'auto'
    cancel(f, t + 10)
    assert f['coins'] == coins and field(f)['run'] is None and field(f)['state'] == 'ready'


def test_only_a_sowing_can_be_taken_back():
    f = equipped()
    fail(f, 'field_cancel', dict(field=field(f)['id'], revision=0), code='nothing_to_cancel')
    cmd(f, 'field_start', dict(field=field(f)['id'], op='cultivate', crop='', revision=0), T0)
    fail(f, 'field_cancel', dict(field=field(f)['id'], revision=field(f)['revision']), T0 + 1, code='nothing_to_cancel')


# ------------------------------------------------------------------------------------------------------------------ V1 / V4
def test_fund_tier_three_costs_two_days_of_income_and_scrolls_cost_12_percent():
    assert catalog.FUND_TIERS == (5, 15, 20, 50, 80)
    assert economy.thresholds(income_ref(30))[2] == 2 * income_ref(30) and len(economy.thresholds(1000)) == 5
    assert catalog.MERCHANT['scroll_k'] == 12
    assert merchant.ENTRIES['scroll_pumpkin_latte']['price'] == 12 * income_ref(14) // 100


# ------------------------------------------------------------------------------------------------------------------ old saves
def test_a_save_made_under_the_old_prices_still_passes_validate_state_and_keeps_working():
    """23 Oct 2026 a constants change broke a tester's farm: nothing saved is compared with the new numbers."""
    f = farm(44, size=30)
    f['objects'] = [o for o in f['objects'] if o['type'] in {'house', 'barn', 'plot'}]
    put(f, 'noodle_shop', 'old_noodle', level=3, x=0, y=20)                     # upgraded when it cost 30 000 and its upkeep was 3 x 1%
    put(f, 'compost_heap', 'old_heap', level=3, x=4, y=20, w=1, h=1)            # upgraded before it became non-upgradable
    put(f, 'pheasantry', 'old_pheasantry', level=2, x=6, y=20)
    cmd(f, 'buy_field', dict(step=0))
    for name in FIELD_MACHINES:
        cmd(f, 'buy_machine', dict(machine=name))
        cmd(f, 'upgrade_machine', dict(machine=name))                           # tier 2 was bought for 30 000
    f['field_machines']['seeder']['tier'] = 3
    # a sowing run and a crop saved by the old code: no price records, no 'gift', no 'built_at'
    t = run_op(f, 'cultivate', T0)
    cmd(f, 'field_start', dict(field=field(f)['id'], op='sow', crop=SOWING, revision=field(f)['revision']), t + 5)
    for key in ('cost', 'fuel', 'gift'):
        field(f)['run'].pop(key)
    # a fund season whose tier 3 was earned at the old threshold (3.0 days) and one that sits between the old and the new threshold
    ref = income_ref(44)
    f['economy'] = dict(billed_day=1, debt=123, seasons={
        '10': dict(level=44, ref=ref, personal=3 * ref, tiers=3, joined=True, common=True),
        '11': dict(level=44, ref=ref, personal=int(2.5 * ref), tiers=2, joined=True, common=False)},
        unlocked=[], titles=[], feast_until=0, stats=dict(upkeep_billed=9, upkeep_paid=9, fund_coins=0, fund_goods=0, fund_village=0, decor=0, feast_xp=0))
    validate_state(f)
    assert economy.base_upkeep(f) > 0 and economy.upkeep(f, T0) > 0
    economy.status(f, T0)
    project(f, f, T0 + 6)
    # the unfinished old sowing can still be taken back (the refund is derived from the catalog), the old building can be cleared
    cancel(f, t + 20)
    assert field(f)['state'] == 'ready' and field(f)['run'] is None
    coins = f['coins']
    cmd(f, 'demolish', dict(object='old_pheasantry', revision=0), T0 + 30)
    assert f['coins'] == coins + (20000 + 10000) // 2
    cmd(f, 'demolish', dict(object='old_heap', revision=0), T0 + 30)
    validate_state(f)
    settle(f, T0 + 40)
    validate_state(f)


def test_an_old_crop_without_a_price_record_is_refunded_from_the_catalog():
    f = equipped()
    t = run_op(f, 'cultivate', T0)
    done = run_op(f, 'sow', t + 5, SOWING)
    crop = field(f)['crop']
    for key in ('cost', 'fuel', 'gift'):
        crop.pop(key)
    validate_state(f)
    coins = f['coins']
    cancel(f, done + 1)
    assert f['coins'] == coins + PRICE
    validate_state(f)
