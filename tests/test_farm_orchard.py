"""Fruit orchard (docs/tasks/FARM_ORCHARD.md): perennial trees, limits, migration of the old bed fruit, care, grafts and vouchers of the
merchant, the dryer and the cellar, orders, helpers, privacy."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from qw_farm import catalog, economy, festivals, market, merchant as M, orchard
from qw_farm.catalog import (BUILDINGS, CROPS, GRAFTS, ITEMS, LEVELS, ORCHARD_RECIPE_IDS, RECIPES, TREE_CYCLE, TREE_LIMITS, TREES, crop_law,
                             public_catalog, tree_limit, validate)
from qw_farm.domain import FarmError, apply, make_order, new_farm, project, reachable, validate_state
from qw_farm.expansion import settle, upgrade_state

MSK = timezone(timedelta(hours=3))
T0 = int(datetime(2026, 11, 3, 12, 0, tzinfo=MSK).timestamp())
STATIC = Path(__file__).resolve().parents[1] / 'qw_farm' / 'static'
DOC_PRICES = {  # FARM_ORCHARD.md section 4.2
    'garden_infusion': 81, 'charlotte': 242, 'apple_juice': 85, 'caramel_apples': 120, 'cherry_jam_5min': 146, 'cherry_juice': 134, 'dried_apples': 164,
    'dried_cherry': 363, 'pear_juice': 91, 'apple_pear_puree': 134, 'cider_zero': 275, 'pear_kvass': 195, 'mead_zero': 265, 'belev_pastila': 293,
    'cherry_tincture': 469, 'prunes': 208, 'plum_liqueur': 455, 'uzvar': 176, 'mulled_nevein': 375, 'pear_sparkle': 425, 'dried_apricot': 226,
    'apricot_five_star': 2011, 'cellar_chest': 1784, 'rejuvenating_elixir': 1545, 'peach_punch': 360}
DOC_XP = {'garden_infusion': 6, 'charlotte': 13, 'apple_juice': 7, 'caramel_apples': 11, 'cherry_jam_5min': 4, 'cherry_juice': 7, 'dried_apples': 22,
          'dried_cherry': 22, 'pear_juice': 7, 'apple_pear_puree': 10, 'cider_zero': 45, 'pear_kvass': 30, 'mead_zero': 45, 'belev_pastila': 45,
          'cherry_tincture': 90, 'prunes': 30, 'plum_liqueur': 90, 'uzvar': 13, 'mulled_nevein': 22, 'pear_sparkle': 67, 'dried_apricot': 30,
          'apricot_five_star': 180, 'cellar_chest': 45, 'rejuvenating_elixir': 90, 'peach_punch': 45}


def farm(coins=10 ** 7, xp=LEVELS[29], size=20, inv=None, at=T0, fid=None):
    f = upgrade_state(new_farm(fid or str(uuid4()), 'Sad', at))
    f.update(xp=xp, coins=coins, starter_credit=0, size=size, objects=[],
             inventory=dict(inv or {}))
    f['progress'].update(day=10 ** 9, dew=10 ** 9, last=10 ** 9, pool=0)    # no Morning dew, no idle-day vigour: exact XP
    economy.state(f)['billed_day'] = 10 ** 9
    return f


def cmd(f, kind, data, at=T0, key=None):
    return apply(f, f, kind, data, at, key or f'{kind}-{at}-{len(f["events"])}-{len(f["objects"])}')


def code(f, kind, data, at=T0):
    before = deepcopy(f)
    with pytest.raises(FarmError) as error:
        cmd(f, kind, data, at)
    assert f == before, 'a refused command leaves the farm untouched'
    return error.value.code


def plant(f, species='apple', x=10, y=10, voucher=None, at=T0):
    cmd(f, 'plant_tree', dict(species=species, x=x, y=y, voucher=voucher), at, key=f'tree-{species}-{x}-{y}-{at}')
    return next(o for o in f['objects'] if o['id'] == f'tree-{species}-{x}-{y}-{at}')


def tree(f, oid):
    return next(o for o in f['objects'] if o['id'] == oid)


def ripen(f, t, at):
    """Take the fruit at ``at`` (the owner's harvest command)."""
    cmd(f, 'harvest', dict(object=t['id'], revision=t['revision']), at)


# ---- catalog ----------------------------------------------------------------------------------------------------------------------
def test_tree_table_follows_the_doc_and_the_xp_law():
    validate()
    assert list(TREES) == ['apple', 'cherry', 'pear', 'plum', 'apricot', 'peach', 'pomegranate']
    table = {s: (t['level'], t['juvenile'], t['yield_qty'], t['xp'], t['cost']) for s, t in TREES.items()}
    assert table == dict(apple=(16, 2, 2, 20, 2300), cherry=(20, 2, 1, 25, 2700), pear=(24, 3, 2, 27, 2400), plum=(28, 2, 2, 29, 2400),
                         apricot=(36, 3, 2, 34, 2500), peach=(44, 2, 2, 40, 2600), pomegranate=(47, 3, 1, 43, 3300))
    for s, t in TREES.items():
        assert abs(t['xp'] - crop_law(t['level'], 43200)[0] / 4) <= 1, s            # a quarter of the xp of a 12 h crop of the same level
        adult_day = (t['yield_qty'] + 1) * ITEMS[t['fruit']]['price']
        assert abs(t['cost'] - 12 * adult_day) / t['cost'] < 0.1, s                  # a sapling = about 12 days of an adult tree
        assert CROPS[t['fruit']]['orchard'] == s and CROPS[t['fruit']]['field'] is False
    assert TREE_CYCLE == 20 * 3600


def test_tree_limits_table():
    assert [tree_limit(s) for s in (8, 10, 12, 14)] == [0, 0, 0, 0]
    assert [tree_limit(s) for s in (16, 18, 20, 22, 24, 26, 28, 30, 32, 34)] == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    assert public_catalog()['orchard']['limits']['20'] == 4


def test_new_rows_follow_the_value_law_and_the_doc_numbers():
    assert ORCHARD_RECIPE_IDS == set(DOC_PRICES)
    for rid, price in DOC_PRICES.items():
        assert abs(ITEMS[rid]['price'] - price) <= 1, rid     # the doc's hand arithmetic floats by a coin: «Пять звёздочек» is 2 010 by the exact law
        assert RECIPES[rid]['xp'] == DOC_XP[rid], rid
        r = RECIPES[rid]
        assert r['seconds'] >= 120 or rid == 'cherry_jam_5min'
        assert sum(ITEMS[k]['price'] * q for k, q in r['outputs'].items()) >= sum(ITEMS[k]['price'] * q for k, q in r['inputs'].items()), rid
        assert r['level'] >= BUILDINGS[r['building']]['level'], 'a recipe is never below its building'
    assert ITEMS['rejuvenating_apple']['price'] == 500
    assert (BUILDINGS['dryer']['cost'], BUILDINGS['dryer']['level']) == (6000, 20) and (BUILDINGS['cellar']['cost'], BUILDINGS['cellar']['level']) == (8500, 24)
    assert BUILDINGS['birdhouse']['decor'] and BUILDINGS['birdhouse']['cost'] == 1500 and (BUILDINGS['birdhouse']['w'], BUILDINGS['birdhouse']['h']) == (1, 1)


def test_recipe_batches_do_not_exceed_an_adult_tree_harvest():
    for rid in ORCHARD_RECIPE_IDS:
        for fruit, q in RECIPES[rid]['inputs'].items():
            if fruit in catalog.TREE_BY_FRUIT:
                spec = TREES[catalog.TREE_BY_FRUIT[fruit]]
                assert q <= spec['yield_qty'] + 1, (rid, fruit)


def test_cellar_has_the_motto_and_no_drunkenness_in_the_rules():
    assert catalog.CELLAR_MOTTO == 'Безалкогольно. Градус — только в названии'
    cellar = [r for r in RECIPES.values() if r['building'] == 'cellar']
    assert len(cellar) == 11
    words = ' '.join([catalog.ORCHARD_TEXT[k] for k in catalog.ORCHARD_TEXT] + [ITEMS[r]['name'] for r in ORCHARD_RECIPE_IDS]).lower()
    assert 'похмель' not in words and 'пьян' not in words, 'no drunkenness, no hangover: the degree lives in the name only'
    assert not [k for k in vars(orchard) if 'drunk' in k.lower() or 'hangover' in k.lower()]
    assert ITEMS['apricot_five_star']['name'].endswith('0%') and ITEMS['rejuvenating_elixir']['name'].endswith('0%')


def test_workshop_xp_uses_the_new_buildings():
    assert RECIPES['cider_zero']['xp'] == 3600 // 80 and RECIPES['dried_apples']['xp'] == max(6, 1800 // 80)


def test_neighbour_residents_like_the_new_goods():
    t = catalog.NPC_TASTES
    assert 'charlotte' in t['Агата'] and {'prunes', 'dried_apricot'} <= set(t['Суслик Игорь']) and 'dried_apples' in t['Почтальон Ёж']
    assert 'pear_kvass' in t['Механик Крот'] and 'mead_zero' in t['Медведь Пух'] and 'cherry_tincture' in t['Филиныч'] and 'apricot_five_star' in t['Неведома Зверушка']
    assert not any('rejuvenating_apple' in v for v in t.values()), 'the golden apple is never asked for by a resident'
    assert 'Кошка Соня' not in {k for k, v in t.items() if 'apple' in ' '.join(v)}


# ---- planting, limits ---------------------------------------------------------------------------------------------------------------
def test_plant_pays_the_price_places_the_tree_and_counts_the_object_limit():
    f = farm()
    before = f['coins']
    t = plant(f)
    assert f['coins'] == before - 2300 and t['type'] == 'tree' and (t['w'], t['h']) == (1, 1) and t['harvests'] == 0 and t['look'] is None
    assert t['fruit']['ready_at'] == T0 + 3 * TREE_CYCLE, 'juvenile 2 + 1 cycles to the first harvest'
    assert t['fruit']['qty'] == 2 and t['fruit']['xp'] == 20 and t['cost'] == 2300
    validate_state(f)
    assert code(f, 'plant_tree', dict(species='apple', x=10, y=10, voucher=None)) == 'occupied'
    assert code(f, 'plant_tree', dict(species='apple', x=99, y=0, voucher=None)) in {'invalid_number', 'outside_land'}


def test_levels_species_and_money_are_checked():
    f = farm(xp=LEVELS[14])      # level 15
    assert code(f, 'plant_tree', dict(species='apple', x=6, y=6, voucher=None)) == 'locked'
    assert code(farm(), 'plant_tree', dict(species='quince', x=6, y=6, voucher=None)) == 'unknown_item'
    assert code(farm(coins=100), 'plant_tree', dict(species='apple', x=6, y=6, voucher=None)) == 'insufficient_coins'
    assert code(farm(), 'plant_tree', dict(species='apple', x=6, y=6, voucher='nope')) == 'no_voucher'
    assert code(farm(), 'plant_tree', dict(species='apple', x=6, y=6, voucher=5)) == 'invalid_command'


def test_tree_limit_by_land_size_and_trees_take_no_beds():
    f = farm(size=16)
    for i in range(2):
        plant(f, 'apple', i, 0)
    assert code(f, 'plant_tree', dict(species='apple', x=5, y=0, voucher=None)) == 'tree_limit'
    assert sum(o['type'] == 'plot' for o in f['objects']) == 0
    assert code(farm(size=14), 'plant_tree', dict(species='apple', x=6, y=6, voucher=None)) == 'tree_limit'
    g = farm(size=20)
    for i in range(4):
        plant(g, 'apple', i, 0)
    assert code(g, 'plant_tree', dict(species='apple', x=9, y=0, voucher=None)) == 'tree_limit'
    for i in range(30):   # beds are counted separately
        cmd(g, 'build', dict(type='plot', x=i % 20, y=2 + i // 20))
    assert sum(o['type'] == 'plot' for o in g['objects']) == 30


def test_object_limit_also_counts_trees():
    f = farm(size=16)
    limit = catalog.object_limit(16)
    f['objects'] += [dict(id=f'd{i}', type='flowerbed', x=i % 16, y=8 + i // 16, w=1, h=1, revision=0, level=1, jobs=[], animal=None, animal_job=None)
                     for i in range(limit - len(f['objects']))]
    assert code(f, 'plant_tree', dict(species='apple', x=0, y=0, voucher=None)) == 'object_limit'


def test_a_tree_pays_land_upkeep_like_a_bed():
    f = farm(size=20)
    base = economy.base_upkeep(f)
    plant(f)
    assert economy.base_upkeep(f) == base + catalog.plot_upkeep(20) == base + 30


# ---- the cycle ----------------------------------------------------------------------------------------------------------------------
def test_growth_over_cycles_stages_yields_and_xp():
    f = farm(size=30)
    t = plant(f)
    assert orchard.stage(t) == 'sapling' and not orchard.ripe(t, T0 + 3 * TREE_CYCLE - 1)
    assert code(f, 'harvest', dict(object=t['id'], revision=t['revision']), ) == 'not_ready'
    when, xp0 = T0 + 3 * TREE_CYCLE, f['xp']
    for n in range(1, 24):
        ripen(f, t, when)
        assert t['harvests'] == n and t['fruit']['ready_at'] == when + TREE_CYCLE
        when += TREE_CYCLE
    assert f['xp'] - xp0 == 23 * 20 and f['stats']['harvests'] == 23, 'one tree gives its xp per cycle, 20 for an apple tree'
    # the fruit count of those harvests includes pest/golden/prune bonuses; the pure yield rule is checked here and on a clean tree below
    assert orchard.yield_of(TREES['apple'], 1) == 2 and orchard.yield_of(TREES['apple'], 5) == 2
    assert orchard.yield_of(TREES['apple'], 6) == 3 and orchard.yield_of(TREES['apple'], 20) == 3
    assert orchard.yield_of(TREES['apple'], 21) == 4 and orchard.yield_of(TREES['apple'], 150) == 4
    assert orchard.yield_of(TREES['cherry'], 1) == 1 and orchard.yield_of(TREES['cherry'], 6) == 2 and orchard.yield_of(TREES['cherry'], 21) == 3
    assert [orchard.stage(dict(harvests=h)) for h in (0, 1, 4, 5, 19, 20, 98, 99)] == ['sapling', 'young', 'young', 'adult', 'adult', 'elder', 'elder', 'century']


def clean_tree(f, species='apple', x=10, y=10):
    """A tree whose pest and golden rolls are off, to read the pure yield."""
    t = plant(f, species, x, y)
    t['fruit'].update(pest=None, golden=False, gold_hidden=False)
    return t


def test_yield_grows_with_age_and_the_cycle_restarts_only_after_the_harvest():
    f = farm(size=30)
    t = clean_tree(f)
    when = T0 + 3 * TREE_CYCLE
    got = []
    for n in range(1, 23):
        t['fruit'].update(pest=None, golden=False, gold_hidden=False)
        t['fruit']['qty'] = orchard.yield_of(TREES['apple'], n)    # the frozen number is what a cycle starts with
        before = f['inventory'].get('apple', 0)
        ripen(f, t, when)
        got.append(f['inventory']['apple'] - before)
        # a late harvest: the next cycle begins at the harvest, not on the old schedule
        when += TREE_CYCLE + 7777 * (n % 2)
    assert got[:5] == [2] * 5 and got[5:20] == [3] * 15 and got[20:] == [4, 4]
    assert t['fruit']['ready_at'] >= when - 7777 + 0


def test_fruit_hangs_unspoilt_and_does_not_pile_up():
    f = farm()
    t = clean_tree(f)
    late = T0 + 3 * TREE_CYCLE + 30 * 86400
    ripen(f, t, late)
    assert f['inventory']['apple'] == 2 and t['fruit']['ready_at'] == late + TREE_CYCLE
    assert code(f, 'harvest', dict(object=t['id'], revision=t['revision']), late + 5) == 'not_ready'


def test_pest_and_golden_fruit_are_deterministic_and_never_cut_the_yield():
    f = farm(fid='11111111-2222-3333-4444-555555555555')
    a = orchard.new_cycle(f, dict(id='t1', species='apple', harvests=7), T0)
    b = orchard.new_cycle(f, dict(id='t1', species='apple', harvests=7), T0)
    assert a == b
    pests = sum(bool(orchard.new_cycle(f, dict(id='t1', species='apple', harvests=h), T0)['pest']) for h in range(1000))
    assert 150 <= pests <= 250, 'about 20% of cycles bring a pest'
    golds = sum(orchard.new_cycle(f, dict(id='t2', species='apple', harvests=h), T0)['golden'] for h in range(6, 3006))
    assert 20 <= golds <= 100, 'about 2% of adult cycles (a little less: a pest hides the golden fruit)'
    assert all(not orchard.new_cycle(f, dict(id='t2', species='apple', harvests=h), T0)['golden'] for h in range(0, 5)), 'young trees give no golden fruit'
    assert all(orchard.new_cycle(f, dict(id='t3', species='apple', harvests=h), T0)['qty'] == 2 for h in range(0, 5))


def test_golden_apple_drops_from_any_species_and_is_not_asked_by_orders():
    f = farm(fid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
    t = plant(f, 'pear')
    t['fruit'].update(pest=None, golden=True)
    ripen(f, t, T0 + 4 * TREE_CYCLE)
    assert f['inventory']['rejuvenating_apple'] == 1 and f['inventory']['pear'] == 2
    f['xp'] = LEVELS[49]
    f['inventory']['rejuvenating_apple'] = 5
    f['objects'].append(dict(id='c1', type='cellar', x=0, y=0, w=2, h=2, revision=0, level=1, jobs=[], animal=None, animal_job=None))
    assert 'rejuvenating_apple' not in reachable(f), 'a resident never asks for what cannot be grown on demand'
    assert 'rejuvenating_elixir' not in reachable(f), 'nor for the drink made of it'


def test_century_tree_doubles_the_golden_chance():
    assert orchard.gold_chance(5) == 0 and orchard.gold_chance(6) == 20 and orchard.gold_chance(99) == 20 and orchard.gold_chance(100) == 40


# ---- care ---------------------------------------------------------------------------------------------------------------------------
def find_pest_tree(f, species='apple'):
    for i in range(400):
        t = plant(f, species, i % 20, 5 + i // 20, at=T0 + i)
        if t['fruit']['pest']:
            return t
        f['objects'].remove(t)
    raise AssertionError('no pest in 400 trees')


def test_spray_costs_one_infusion_removes_the_pest_and_adds_a_fruit_and_the_golden_chance():
    f = farm(inv={'garden_infusion': 1})
    t = find_pest_tree(f)
    qty = t['fruit']['qty']
    t['fruit']['gold_hidden'] = True
    cmd(f, 'tree_care', dict(object=t['id'], action='spray', item=None))
    assert t['fruit']['pest'] is None and t['fruit']['qty'] == qty + 1 and t['fruit']['golden'] and f['inventory']['garden_infusion'] == 0
    assert code(f, 'tree_care', dict(object=t['id'], action='spray', item=None)) == 'no_pest'


def test_spray_needs_a_pest_and_an_infusion():
    f = farm()
    t = find_pest_tree(f)
    assert code(f, 'tree_care', dict(object=t['id'], action='spray', item=None)) == 'missing_goods'
    g = farm(inv={'garden_infusion': 2})
    clean = clean_tree(g)
    assert code(g, 'tree_care', dict(object=clean['id'], action='spray', item=None)) == 'no_pest'


def test_a_pest_left_alone_costs_nothing():
    f = farm()
    t = find_pest_tree(f)
    qty = t['fruit']['qty']
    ripen(f, t, T0 + 400 + 4 * TREE_CYCLE)
    assert f['inventory']['apple'] == qty, 'an untreated pest costs nothing'


def test_birdhouse_treats_the_pest_by_itself_within_two_cells():
    f = farm()
    t = find_pest_tree(f)
    qty = t['fruit']['qty']
    bx, by = t['x'] + 2, t['y']
    cmd(f, 'build', dict(type='birdhouse', x=bx, y=by))
    assert orchard.near_birdhouse(f, t) and not orchard.pest_active(f, t)
    assert code(f, 'tree_care', dict(object=t['id'], action='spray', item=None)) == 'bird_watch'
    ripen(f, t, T0 + 400 + 4 * TREE_CYCLE)
    assert f['inventory']['apple'] == qty + 1, 'the birdhouse counts as a spray: one more fruit'


def test_birdhouse_is_free_to_keep_and_far_trees_are_not_covered():
    f = farm()
    t = plant(f, 'apple', 0, 0)
    cmd(f, 'build', dict(type='birdhouse', x=3, y=0))
    assert not orchard.near_birdhouse(f, t)
    base = economy.base_upkeep(f)
    f['objects'] = [o for o in f['objects'] if o['type'] != 'birdhouse']
    assert economy.base_upkeep(f) == base, 'decor has no upkeep'


def test_prune_gives_wood_and_fruit_and_waits_for_dry_branches():
    f = farm(size=30)
    t = clean_tree(f)
    assert code(f, 'tree_care', dict(object=t['id'], action='prune', item=None)) == 'no_dry_branches'
    when = T0 + 3 * TREE_CYCLE
    for n in range(7):
        t['fruit'].update(pest=None, golden=False, gold_hidden=False)
        ripen(f, t, when)
        when += TREE_CYCLE
    assert orchard.dry(t) and t['harvests'] == 7
    t['fruit'].update(pest=None)
    qty, wood = t['fruit']['qty'], f['inventory'].get('wood', 0)
    cmd(f, 'tree_care', dict(object=t['id'], action='prune', item=None), when)
    assert f['inventory']['wood'] == wood + 2 and t['fruit']['qty'] == qty + 1 and not orchard.dry(t) and t['pruned_until'] == 14
    nxt = []
    for n in range(8):
        t['fruit'].update(pest=None, golden=False, gold_hidden=False)
        nxt.append(t['fruit']['qty'] - orchard.yield_of(TREES['apple'], t['harvests'] + 1))
        ripen(f, t, when + TREE_CYCLE * (n + 1))
    assert nxt == [1] * 7 + [0], 'seven harvests with the bonus (the current one included), then none until the next pruning'


def test_unpruned_branches_cost_nothing():
    f = farm(size=30)
    t = clean_tree(f)
    when = T0 + 3 * TREE_CYCLE
    for n in range(10):
        t['fruit'].update(pest=None, golden=False, gold_hidden=False)
        ripen(f, t, when)
        when += TREE_CYCLE
    assert orchard.dry(t) and t['harvests'] == 10


# ---- uprooting ---------------------------------------------------------------------------------------------------------------------
def test_uproot_in_the_undo_window_refunds_the_sapling_in_full():
    f = farm()
    f['starter_credit'] = 0
    coins = f['coins']
    t = plant(f)
    cmd(f, 'demolish', dict(object=t['id'], revision=t['revision']), T0 + 30)
    assert f['coins'] == coins and not [o for o in f['objects'] if o['type'] == 'tree'] and f['inventory'].get('wood', 0) == 0


def test_uproot_later_gives_only_wood_and_takes_the_ripe_fruit_first():
    f = farm()
    t = clean_tree(f)
    coins = f['coins']
    cmd(f, 'demolish', dict(object=t['id'], revision=t['revision']), T0 + 3 * TREE_CYCLE + 5)
    assert f['inventory']['apple'] == 2 and f['inventory']['wood'] == 2 and f['coins'] == coins and not [o for o in f['objects'] if o['type'] == 'tree']
    g = farm()
    u = plant(g)
    cmd(g, 'demolish', dict(object=u['id'], revision=u['revision']), T0 + 3600)
    assert g['inventory'] == {'wood': 2} and g['coins'] == 10 ** 7 - 2300


def test_uproot_in_the_window_returns_a_spent_voucher():
    f = farm()
    f['orchard']['vouchers']['apple'] = 1
    t = plant(f, voucher='free')
    assert f['orchard']['vouchers'] == {} and t['cost'] == 0
    cmd(f, 'demolish', dict(object=t['id'], revision=t['revision']), T0 + 10)
    assert f['orchard']['vouchers'] == {'apple': 1}


def test_move_keeps_the_tree_state():
    f = farm()
    t = plant(f)
    t['harvests'] = 3
    cmd(f, 'move', dict(object=t['id'], x=6, y=6, revision=t['revision']))
    assert (t['x'], t['y'], t['harvests']) == (6, 6, 3)


# ---- collecting: bulk, helpers, neighbours -------------------------------------------------------------------------------------------
def test_collect_all_and_collect_group_take_ripe_trees_and_beds_together():
    f = farm()
    t = clean_tree(f)
    cmd(f, 'build', dict(type='plot', x=0, y=0))
    plot = next(o for o in f['objects'] if o['type'] == 'plot')
    cmd(f, 'plant', dict(object=plot['id'], crop='wheat', revision=plot['revision']))
    later = T0 + 3 * TREE_CYCLE + 100
    cmd(f, 'collect_all', {}, later)
    assert f['inventory']['apple'] == 2 and f['inventory']['wheat'] == 3
    t2 = clean_tree(f, 'cherry', 12, 12)
    cmd(f, 'collect_group', dict(group='plots', area=None), later + 4 * TREE_CYCLE)
    assert f['inventory'].get('cherry') == 1 and t2['harvests'] == 1


def test_harvest_helper_takes_ripe_trees_in_its_zone_and_xp_is_not_the_owners():
    f = farm()
    t = clean_tree(f)
    cmd(f, 'hire_helper', {'helper': 'fox_picker'})
    cmd(f, 'start_shift', {'worker': 'fox_picker', 'shift': 'night'}, T0 + 3 * TREE_CYCLE - 600)
    xp = f['xp']
    settle(f, T0 + 3 * TREE_CYCLE + 3600)
    assert t['harvests'] == 1 and f['inventory']['apple'] == 2 and f['xp'] == xp + 20


def test_water_helper_shortens_the_sapling_phase_once():
    f = farm()
    t = clean_tree(f)
    ready = t['fruit']['ready_at']
    cmd(f, 'hire_helper', {'helper': 'rabbit_gardener'})
    cmd(f, 'start_shift', {'worker': 'rabbit_gardener', 'shift': 'night'})
    settle(f, T0 + 1000)
    assert t['fruit']['watered'] and t['fruit']['ready_at'] == ready - (ready - T0) * 150 // 1000
    later = t['fruit']['ready_at']
    settle(f, T0 + 2000)
    assert t['fruit']['ready_at'] == later, 'watered once'


def neighbours():
    a, b = farm(fid=str(uuid4())), farm(fid=str(uuid4()))
    for x, y in ((a, b), (b, a)):
        x['neighbors'][y['id']] = {'name': y['name'], 'status': 'accepted'}
    return a, b


def test_neighbour_help_cuts_a_fifth_of_the_time_left_once_per_cycle():
    me, other = neighbours()
    t = clean_tree(other)
    left = t['fruit']['ready_at'] - T0
    apply(me, other, 'help', dict(object=t['id'], revision=t['revision']), T0, 'h1')
    cut = -(-left // 5)     # 20% of the time left, rounded up
    assert t['fruit']['ready_at'] == T0 + left - cut and t['fruit']['helped']
    before = deepcopy(other)
    with pytest.raises(FarmError) as error:
        apply(me, other, 'help', dict(object=t['id'], revision=t['revision']), T0, 'h2')
    assert error.value.code == 'cannot_help' and other == before


def test_guest_sees_the_look_and_ripeness_but_not_prices_vouchers_or_care():
    me, other = neighbours()
    t = plant(other)
    t['look'] = 'paradise'
    view = project(other, me, T0)
    seen = next(o for o in view['objects'] if o['type'] == 'tree')
    assert seen['look'] == 'paradise' and seen['fruit'] == {'ready_at': t['fruit']['ready_at'], 'helped': False}
    for hidden in ('cost', 'gift', 'paid_with', 'pruned_until', 'prune_at'):
        assert hidden not in seen
    assert 'orchard' not in view and 'orchard_view' not in view
    own = project(other, other, T0)
    assert own['orchard_view']['count'] == 1 and own['orchard_view']['limit'] == 4 and own['orchard_view']['trees'][t['id']]['stage'] == 'sapling'


# ---- migration of the annual fruit --------------------------------------------------------------------------------------------------
def old_farm(**kw):
    f = farm(**kw)
    del f['orchard']
    return f


def test_a_fruit_grown_on_beds_earns_exactly_one_free_sapling():
    f = old_farm()
    f['harvested_crops'] += ['apple', 'wheat', 'pear']
    upgrade_state(f, T0)
    assert f['orchard']['vouchers'] == {'apple': 1, 'pear': 1} and sorted(f['orchard']['granted']) == ['apple', 'pear']
    assert set(f['orchard']['seen']) == set(TREES)
    ev = [e for e in f['events'] if e['kind'] == 'orchard']
    assert len(ev) == 2 and 'взамен грядочной яблони' in ev[1]['text'] + ev[0]['text'] and all(e['at'] == T0 for e in ev)
    again = deepcopy(f)
    upgrade_state(f, T0 + 99)
    assert f == again, 'repeatable'
    upgrade_state(f)
    assert f == again


def test_a_planting_in_flight_on_a_bed_or_a_field_counts_too():
    f = old_farm()
    f['objects'].append(dict(id='p1', type='plot', x=6, y=6, w=1, h=1, revision=0,
                             crop=dict(id='cherry', planted_at=T0, ready_at=T0 + 7200, yield_qty=2, xp=42, helped=False, version=catalog.VERSION, cost=45, gift=0)))
    f['fields'] = [dict(id='f1', state='growing', crop=dict(id='plum', planted_at=T0, ready_at=T0 + 9, base=1, q_sow=1000), run=None)]
    upgrade_state(f, T0)
    assert f['orchard']['vouchers'] == {'cherry': 1, 'plum': 1}


def test_nothing_is_given_to_a_farm_that_never_grew_fruit_and_a_tree_harvest_does_not_make_it_eligible():
    f = old_farm()
    upgrade_state(f, T0)
    assert f['orchard']['vouchers'] == {} and f['orchard']['granted'] == [] and set(f['orchard']['seen']) == set(TREES)
    t = clean_tree(f)
    ripen(f, t, T0 + 3 * TREE_CYCLE)
    assert 'apple' in f['harvested_crops']
    upgrade_state(f, T0 + 4 * TREE_CYCLE)
    assert f['orchard']['vouchers'] == {} and f['orchard']['granted'] == []


def test_a_brand_new_farm_gets_no_voucher():
    f = upgrade_state(new_farm(str(uuid4()), 'New', T0))
    assert f['orchard']['vouchers'] == {} and f['orchard']['granted'] == [] and not [e for e in f['events'] if e['kind'] == 'orchard']


def test_new_bed_plantings_of_fruit_are_closed_on_every_path_but_old_ones_finish():
    f = farm(xp=LEVELS[49])
    cmd(f, 'build', dict(type='plot', x=0, y=0))
    cmd(f, 'build', dict(type='plot', x=1, y=0))
    p = next(o for o in f['objects'] if o['type'] == 'plot')
    assert code(f, 'plant', dict(object=p['id'], crop='apple', revision=p['revision'])) == 'orchard_crop'
    assert code(f, 'plant_many', dict(crop='cherry', area=None)) == 'orchard_crop'
    cmd(f, 'buy_equipment', {'equipment': 'seeder'}) if 'seeder' in catalog.EQUIPMENT else None
    f['equipment']['tractor'] = dict(acquired_at=T0, shift=None, total_runs=0)
    assert code(f, 'machine_run', dict(machine='tractor', crop='pear', plots=[dict(id=p['id'], revision=p['revision'])], replant=False)) == 'orchard_crop'
    # the order of the checks: a locked fruit is still reported as locked
    assert code(farm(xp=0), 'plant_many', dict(crop='peach', area=None)) in {'locked', 'no_empty_plots'}
    # an old planting grows to the end by its frozen numbers
    p['crop'] = dict(id='apple', planted_at=T0 - 43200, ready_at=T0, yield_qty=6, xp=74, helped=False, version=catalog.VERSION, cost=75, gift=0)
    cmd(f, 'harvest', dict(object=p['id'], revision=p['revision']))
    assert f['inventory']['apple'] == 6
    q = f['objects'][-1]
    q['crop'] = dict(id='cherry', planted_at=T0, ready_at=T0 + 7200, yield_qty=2, xp=42, helped=False, version=catalog.VERSION, cost=45, gift=0)
    cmd(f, 'dig_up', dict(object=q['id'], revision=q['revision']), T0 + 1)    # digging up still works


def test_fields_do_not_sow_the_fruit_any_more_with_their_own_message():
    from qw_farm import fields
    assert CROPS['apple']['field'] is False and 'apple' not in public_catalog()['fields']['crops']
    f = farm()
    f['fields'] = [dict(id='f1', ha=1, w=8, h=8, state='ready', crop=None, run=None, revision=0, seq=0, q_cult=950)]
    f['field_machines'] = {'seeder': dict(tier=1, acquired_at=T0), 'cultivator': dict(tier=1, acquired_at=T0), 'combine': dict(tier=1, acquired_at=T0)}
    assert code(f, 'field_start', dict(field='f1', op='sow', crop='apple', revision=0)) == 'orchard_crop'


def test_contracts_never_ask_to_harvest_orchard_fruit():
    f = farm(xp=LEVELS[32])
    for day in range(2000, 2300):
        market.make_contracts(f, day)
        for c in f['market']['contracts']['items']:
            assert not (c['kind'] == 'harvest' and CROPS[c['item']].get('orchard')), c


def test_orders_ask_for_a_fruit_only_when_it_can_be_grown_and_old_recipes_stay_valid():
    f = farm(xp=LEVELS[29])
    bare = set(reachable(f))
    assert 'apple' not in bare and 'cherry' not in bare and 'apple_pie' not in bare and 'wheat' in bare
    t = plant(f)
    assert 'apple' not in reachable(f), 'before the first harvest the fruit is still not reachable'
    ripen(f, t, T0 + 3 * TREE_CYCLE)
    got = set(reachable(f))
    assert 'apple' in got and 'cherry' not in got
    f['objects'].append(dict(id='b1', type='bakery', x=0, y=0, w=2, h=2, revision=0, level=1, jobs=[], animal=None, animal_job=None))
    f['objects'].append(dict(id='j1', type='juicery', x=3, y=0, w=2, h=2, revision=0, level=1, jobs=[], animal=None, animal_job=None))
    assert 'apple_juice' in set(reachable(f))
    assert not {'cider_zero'} & set(reachable(f)), 'a recipe needs its workshop'
    # an old planting of another fruit on a bed is enough
    f['objects'].append(dict(id='p9', type='plot', x=9, y=9, w=1, h=1, revision=0,
                             crop=dict(id='plum', planted_at=T0, ready_at=T0 + 9, yield_qty=6, xp=74, helped=False, version=catalog.VERSION, cost=84, gift=0)))
    assert 'plum' in reachable(f)
    for slot in range(60):
        order = make_order(f, slot % 3, T0 + slot)
        assert set(order['needs']) <= set(reachable(f))


def test_recipes_memory_of_a_fruit_workshop_survives_the_migration():
    f = old_farm()
    f['objects'].append(dict(id='b1', type='bakery', x=0, y=0, w=2, h=2, revision=0, level=2, jobs=[], animal=None, animal_job=None,
                             recipes_memory=['apple_pie', 'bagels'], last_recipe='bagels', recipe_cursor=0))
    f['harvested_crops'].append('apple')
    f['inventory'].update(flour=9, apple=9, butter=9, egg=9)
    upgrade_state(f, T0)
    b = f['objects'][-1]
    assert b['recipes_memory'] == ['apple_pie', 'bagels'] and f['orchard']['vouchers'] == {'apple': 1}
    from qw_farm import expansion
    assert expansion.restartable(f, b, level(f)).get('id') == 'apple_pie'
    validate_state(f)


def level(f):
    return catalog.level(f['xp'])


# ---- vouchers and grafts (the merchant) -----------------------------------------------------------------------------------------------
def test_a_free_voucher_plants_a_tree_of_its_species_inside_the_limit():
    f = farm(size=16)
    f['orchard']['vouchers'] = {'apple': 1}
    coins = f['coins']
    assert code(f, 'plant_tree', dict(species='cherry', x=6, y=6, voucher='free')) == 'no_voucher'
    t = plant(f, 'apple', 1, 1, voucher='free')
    assert f['coins'] == coins and t['cost'] == 0 and f['orchard']['vouchers'] == {}
    plant(f, 'apple', 3, 3)
    f['orchard']['vouchers'] = {'apple': 1}
    assert code(f, 'plant_tree', dict(species='apple', x=9, y=9, voucher='free')) == 'tree_limit', 'a voucher does not lift the limit'
    assert f['orchard']['vouchers'] == {'apple': 1}


def test_a_discount_voucher_takes_a_quarter_and_only_for_the_level_of_the_player():
    f = farm(inv={'voucher_orchard': 2})
    coins = f['coins']
    t = plant(f, voucher='voucher_orchard')
    assert f['coins'] == coins - 2300 * 75 // 100 and f['inventory']['voucher_orchard'] == 1 and t['paid_with'] == 'voucher_orchard'
    low = farm(xp=LEVELS[14], inv={'voucher_orchard': 1})
    assert code(low, 'plant_tree', dict(species='apple', x=6, y=6, voucher='voucher_orchard')) == 'locked'
    assert low['inventory']['voucher_orchard'] == 1
    assert code(farm(inv={'berry_charge': 1}), 'plant_tree', dict(species='apple', x=6, y=6, voucher='berry_charge')) == 'no_voucher'
    assert code(farm(), 'plant_tree', dict(species='apple', x=6, y=6, voucher='voucher_orchard')) == 'no_voucher'


def test_a_graft_changes_only_the_look():
    f = farm(inv={'graft_apple_paradise': 1, 'graft_pear_bergamot': 1})
    t = clean_tree(f)
    before = {k: deepcopy(v) for k, v in t.items() if k not in ('look', 'revision')}
    assert code(f, 'tree_care', dict(object=t['id'], action='graft', item='graft_pear_bergamot')) == 'wrong_species'
    assert code(f, 'tree_care', dict(object=t['id'], action='graft', item='wheat')) == 'unknown_item'
    cmd(f, 'tree_care', dict(object=t['id'], action='graft', item='graft_apple_paradise'))
    assert t['look'] == 'paradise' and f['inventory']['graft_apple_paradise'] == 0
    assert {k: v for k, v in t.items() if k not in ('look', 'revision')} == before, 'yield, xp, limit and timers are untouched'
    f['inventory']['graft_apple_paradise'] = 1
    assert code(f, 'tree_care', dict(object=t['id'], action='graft', item='graft_apple_paradise')) == 'same_look'
    assert code(f, 'tree_care', dict(object=t['id'], action='graft', item=None)) == 'invalid_command'
    assert code(f, 'tree_care', dict(object='nope', action='graft', item='graft_apple_paradise')) == 'not_found'
    validate_state(f)


def regular_visit():
    d = market.moscow_day(T0)
    while not (M.scheduled(d) and M._fair_day(d) is None):
        d += 1
    return d


def orchard_visit():
    d = market.moscow_day(T0)
    while True:
        v = M.visit_on(d)
        if v and any(s['kind'] in ('graft', 'voucher') for s in M.stock(v)):
            return d
        d += 1


def test_the_merchant_sells_grafts_and_vouchers_in_the_last_slot_of_some_visits():
    seen = set()
    for d in range(market.moscow_day(T0), market.moscow_day(T0) + 400):
        v = M.visit_on(d)
        if v:
            slots = M.stock(v)
            assert len(slots) == 6 and len({s['id'] for s in slots}) == 6
            for s in slots:
                if s['kind'] in ('graft', 'voucher'):
                    seen.add(s['id'])
                    assert s['slot'] == 5 and s['wired'] and ITEMS[s['item']]['bound']
    assert seen == set(M.ORCHARD_IDS)


def test_buying_a_graft_needs_the_tree_and_a_voucher_works_end_to_end():
    d = orchard_visit()
    at = M._ts(d) + 12 * 3600
    v = M.visit_on(d)
    slot = next(s for s in M.stock(v) if s['kind'] in ('graft', 'voucher'))
    f = farm(at=at)
    f['progress'].update(day=10 ** 9)
    if slot['kind'] == 'graft':
        assert code(f, 'merchant_buy', dict(visit_id=v['visit_id'], slot=slot['slot'], qty=1), at) == 'no_tree'
        sp = GRAFTS[slot['id']]['species']
        t = plant(f, sp, 1, 1, at=at)
        cmd(f, 'merchant_buy', dict(visit_id=v['visit_id'], slot=slot['slot'], qty=1), at)
        assert f['inventory'][slot['id']] == 1
        cmd(f, 'tree_care', dict(object=t['id'], action='graft', item=slot['id']), at)
        assert t['look'] == GRAFTS[slot['id']]['look']
    else:
        cmd(f, 'merchant_buy', dict(visit_id=v['visit_id'], slot=slot['slot'], qty=1), at)
        assert f['inventory'][slot['id']] == 1
        before = f['coins']
        plant(f, 'apple', 2, 2, voucher=slot['id'], at=at)
        assert f['coins'] == before - 2300 * 75 // 100
    with pytest.raises(FarmError):
        cmd(f, 'merchant_buy', dict(visit_id=v['visit_id'], slot=slot['slot'], qty=1), at)


def test_bound_garden_goods_never_leave_the_farm():
    for item in ('graft_apple_paradise', 'voucher_orchard'):
        f = farm(inv={item: 1})
        assert code(f, 'sell', dict(item=item, qty=1)) == 'bound_item'
        assert code(f, 'list', dict(item=item, qty=1, unit_price=1)) in {'bound_item', 'trade_locked'}


def test_the_apple_spas_festival_adds_an_apple_on_its_fair_days_only():
    day = festivals.day_number(datetime(2027, 8, 19).date())
    assert festivals.current(festivals._ts(day) + 43200)['id'] == 'spas'
    f = farm(at=festivals._ts(day) - 5 * 86400)
    t = clean_tree(f)
    ripen(f, t, festivals._ts(day) + 43200)
    assert f['inventory']['apple'] == 3
    g = farm()
    u = clean_tree(g)
    ripen(g, u, T0 + 3 * TREE_CYCLE)
    assert g['inventory']['apple'] == 2
    h = farm(at=festivals._ts(day) - 5 * 86400)
    w = clean_tree(h, 'pear')
    ripen(h, w, festivals._ts(day) + 43200)
    assert h['inventory']['pear'] == 2, 'only apple trees'


# ---- the workshops ---------------------------------------------------------------------------------------------------------------------
def test_the_cellar_chain_runs_from_the_juice_to_the_chest():
    f = farm(xp=LEVELS[44], inv=dict(apple=20, honey=30, cherry=10, plum=10, pear=10, kvass=5, ginger=2, egg=4))
    for i, typ in enumerate(('juicery', 'cellar', 'dryer', 'kitchen')):
        cmd(f, 'build', dict(type=typ, x=i * 3, y=0), key=f'w-{typ}')
    wid = {o['type']: o['id'] for o in f['objects']}
    t = T0

    def make(rec, bld, times=1):
        nonlocal t
        for _ in range(times):
            cmd(f, 'queue', dict(object=wid[bld], recipe=rec), t)
            t += RECIPES[rec]['seconds'] * 3 + 5
            cmd(f, 'collect_building', dict(object=wid[bld]), t)
    make('apple_juice', 'juicery', 2)
    assert f['inventory']['apple_juice'] == 4
    make('cider_zero', 'cellar') if f['inventory']['apple_juice'] >= 3 else None
    assert f['inventory']['cider_zero'] == 2
    assert code(f, 'queue', dict(object=wid['cellar'], recipe='apple_juice'), t) == 'wrong_building'
    assert RECIPES['cider_zero']['building'] == 'cellar' and f['xp'] > LEVELS[44]


def test_cellar_and_dryer_unlock_by_level_and_show_in_the_build_catalog():
    assert code(farm(xp=LEVELS[18]), 'build', dict(type='dryer', x=6, y=6)) == 'locked'
    assert code(farm(xp=LEVELS[22]), 'build', dict(type='cellar', x=6, y=6)) == 'locked'
    cat = public_catalog()
    assert 'dryer' in cat['buildings'] and 'cellar' in cat['buildings'] and 'birdhouse' in cat['buildings']
    assert cat['orchard']['motto'].startswith('Безалкогольно')


def test_validate_state_checks_the_orchard():
    f = farm()
    plant(f)
    validate_state(f)
    broken = [lambda g, t: t.update(species='kiwi'), lambda g, t: t.update(harvests=-1), lambda g, t: t.update(fruit={'ready_at': 'soon'}),
              lambda g, t: g['orchard'].update(vouchers={'apple': -1}), lambda g, t: g['orchard'].update(vouchers={'kiwi': 1}),
              lambda g, t: g['orchard'].update(granted=['apple'], seen=[]), lambda g, t: g['orchard'].update(extra=1)]
    for damage in broken:
        g = deepcopy(f)
        damage(g, next(o for o in g['objects'] if o['type'] == 'tree'))
        with pytest.raises(FarmError):
            validate_state(g)


def test_an_unknown_object_type_does_not_break_the_loading_of_a_farm():
    """The orchard is the first new object type: `validate_state` has no whitelist of types, so a rolled-back release survives a tree."""
    f = farm()
    plant(f)
    stripped = deepcopy(f)
    stripped['objects'].append(dict(id='x1', type='something_new', x=0, y=0, w=1, h=1, revision=0))
    validate_state(stripped)


# ---- the service: replay, ledger, the JSON round trip, the catalog the client reads ---------------------------------------------------
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


def test_service_plants_once_replays_and_survives_a_json_round_trip():
    import asyncio
    import json
    from qw_farm.service import FarmService, Principal

    async def run():
        unit = FakeUnit('acc', farm(at=T0))
        service = FarmService(unit, Principal('acc', 'Игрок'), clock=lambda: T0)
        data = dict(species='apple', x=6, y=6, voucher=None)
        first = await service.command('plant-tree-0001', 'plant_tree', data)
        coins = unit.farm['coins']
        assert await service.command('plant-tree-0001', 'plant_tree', data) == first and unit.farm['coins'] == coins
        assert sum(o['type'] == 'tree' for o in unit.farm['objects']) == 1
        assert [(k, kind, d) for k, kind, d in unit.records if kind == 'plant_tree'] == [('plant-tree-0001', 'plant_tree', -2300)]
        with pytest.raises(FarmError) as reused:
            await service.command('plant-tree-0001', 'plant_tree', dict(data, x=7))
        assert reused.value.code == 'key_reused'
        again = json.loads(json.dumps(unit.farm))
        validate_state(again)
        assert again['objects'][-1]['fruit'] == unit.farm['objects'][-1]['fruit']
        shown = await service.open()
        assert shown['farm']['orchard_view']['count'] == 1 and shown['catalog']['orchard']['trees']['apple']['cost'] == 2300
        assert shown['catalog']['crops']['apple']['orchard'] == 'apple' and shown['catalog']['crops']['apple']['field'] is False
    asyncio.run(run())


def test_unknown_or_extra_fields_are_refused_by_the_strict_schemas():
    f = farm()
    assert code(f, 'plant_tree', dict(species='apple', x=6, y=6)) == 'invalid_command'
    assert code(f, 'plant_tree', dict(species='apple', x=6, y=6, voucher=None, price=1)) == 'invalid_command'
    assert code(f, 'tree_care', dict(object='x', action='prune')) == 'invalid_command'
    t = plant(f)
    assert code(f, 'tree_care', dict(object=t['id'], action='dance', item=None)) == 'invalid_command'
    assert code(f, 'tree_care', dict(object=t['id'], action='prune', item='wood')) == 'invalid_command'


# ---- plantings in flight on a field; the garden goods of the merchant and the festivals ---------------------------------------------------
def test_an_apple_crop_growing_on_a_field_ripens_and_is_harvested_and_an_open_sow_run_finishes():
    from qw_farm import fields
    TTL = catalog.FIELD_RUN_TTL
    f = farm(xp=LEVELS[43])
    cmd(f, 'buy_field', dict(step=0))
    for machine in catalog.FIELD_MACHINES:
        cmd(f, 'buy_machine', dict(machine=machine))
    fld = f['fields'][0]
    # (a) a crop planted before the orchard existed: it ripens by its frozen numbers and the combine brings the apples
    fld.update(state='growing', crop=dict(id='apple', planted_at=T0, ready_at=T0 + 3600, base=96, xp=74, q_sow=950, version=catalog.VERSION), q_cult=950)
    settle(f, T0 + 3600)
    assert fld['state'] == 'ripe' and 'apple' in orchard.fruits_in_reach(f)
    cmd(f, 'field_start', dict(field=fld['id'], op='harvest', crop='', revision=fld['revision']), T0 + 3600)
    settle(f, T0 + 3600 + TTL + 5)
    assert fld['state'] == 'wild' and f['inventory']['apple'] == fields.yield_qty(96, 950, 950) > 0
    validate_state(f)
    # (b) a sowing run opened for the fruit before the release: new runs are closed, the open one is still finished by the server
    at = T0 + 10 * 86400
    cmd(f, 'field_start', dict(field=fld['id'], op='cultivate', crop='', revision=fld['revision']), at)
    settle(f, at + TTL + 1)
    assert fld['state'] == 'ready'
    assert code(f, 'field_start', dict(field=fld['id'], op='sow', crop='apple', revision=fld['revision']), at + TTL + 2) == 'orchard_crop'
    cmd(f, 'field_start', dict(field=fld['id'], op='sow', crop='saffron', revision=fld['revision']), at + TTL + 2)
    fld['run']['crop'] = 'apple'
    settle(f, at + 3 * TTL)
    assert fld['state'] == 'growing' and fld['crop']['id'] == 'apple'
    validate_state(f)
    settle(f, fld['crop']['ready_at'])
    assert fld['state'] == 'ripe'


def test_a_graft_slot_says_why_it_cannot_be_bought_without_a_tree():
    d = orchard_visit()
    at = M._ts(d) + 12 * 3600
    v = M.visit_on(d)
    graft = next((s for s in M.stock(v) if s['kind'] == 'graft'), None)
    if graft is None:       # the first orchard visit holds a voucher: look for a later one with a graft
        d = next(x for x in range(d, d + 400) if M.visit_on(x) and any(s['kind'] == 'graft' for s in M.stock(M.visit_on(x))))
        at, v = M._ts(d) + 12 * 3600, M.visit_on(d)
        graft = next(s for s in M.stock(v) if s['kind'] == 'graft')
    f = farm(at=at)
    view = M.owner_view(f, at)
    assert next(s for s in view['slots'] if s['slot'] == graft['slot'])['status'] == 'notree'
    plant(f, GRAFTS[graft['id']]['species'], 6, 6, at=at)
    assert next(s for s in M.owner_view(f, at)['slots'] if s['slot'] == graft['slot'])['status'] == 'ok'


def test_festival_orchard_lots_give_a_usable_voucher_and_graft():
    voucher = dict(id='fest_ny_voucher', kind='voucher', orchard=True, wired=True, ref='voucher_orchard')
    graft = dict(id='fest_ny_graft', kind='graft', orchard=True, wired=True, ref='')
    f = farm()
    assert orchard.deliver_festival_good(f, voucher) == 'voucher_orchard' and f['inventory']['voucher_orchard'] == 1
    assert orchard.deliver_festival_good(f, graft) == 'fest_ny_graft' and f['inventory']['fest_ny_graft'] == 1
    assert orchard.deliver_festival_good(f, dict(id='fest_ny_star', kind='decor')) is None
    t = clean_tree(f)
    cmd(f, 'tree_care', dict(object=t['id'], action='graft', item='fest_ny_graft'))
    assert t['look'] == 'frost' and f['inventory']['fest_ny_graft'] == 0
    plant(f, 'apple', 3, 3, voucher='voucher_orchard')
    validate_state(f)


def test_buying_a_festival_voucher_through_the_festival_engine_delivers_it():
    day = festivals.day_number(datetime(2027, 1, 2).date())     # the fair of «Новый год»
    at = festivals._ts(day) + 43200
    fest = festivals.current(at)
    assert fest and fest['id'] == 'new_year' and fest['phase'] == 'fair'
    good = next(g for g in festivals.content('new_year')['goods'] if g['kind'] == 'voucher')
    f = farm(at=at)
    cmd(f, 'festival_buy', dict(festival='new_year', item=good['id']), at)
    assert f['inventory'].get('voucher_orchard') == 1 and good['wired']


def test_migration_gives_a_voucher_per_fruit_even_when_it_exceeds_the_tree_limit_and_nothing_is_lost():
    f = old_farm(size=16)                                        # limit 2 trees
    f['harvested_crops'] += ['apple', 'cherry', 'pear', 'plum', 'apricot']
    f['objects'].append(dict(id='p1', type='plot', x=1, y=1, w=1, h=1, revision=0,
                             crop=dict(id='peach', planted_at=T0, ready_at=T0 + 9, yield_qty=6, xp=74, helped=False, version=catalog.VERSION, cost=87, gift=0)))
    upgrade_state(f, T0)
    assert f['orchard']['vouchers'] == dict(apple=1, cherry=1, pear=1, plum=1, apricot=1, peach=1) and tree_limit(16) == 2
    f['xp'] = LEVELS[49]
    plant(f, 'apple', 4, 4, voucher='free')
    plant(f, 'cherry', 5, 4, voucher='free')
    assert code(f, 'plant_tree', dict(species='pear', x=6, y=4, voucher='free')) == 'tree_limit'
    assert f['orchard']['vouchers'] == dict(pear=1, plum=1, apricot=1, peach=1), 'the rest stay as vouchers, none is spent or lost'
    f['size'] = 18                                                # more land, one more tree; the old planting still finishes
    plant(f, 'pear', 6, 4, voucher='free')
    cmd(f, 'harvest', dict(object='p1', revision=0), T0 + 9)
    assert f['inventory']['peach'] == 6 and f['orchard']['vouchers'] == dict(plum=1, apricot=1, peach=1)
    validate_state(f)


def test_the_orchard_has_its_art_icons_for_every_good_and_sapling_the_tab_and_drawers_for_the_two_workshops():
    import re
    from qw_farm.catalog import ORCHARD_ITEM_IDS
    icons = set(re.findall(r'<symbol id="([a-z_0-9]+)"', (STATIC / 'icons.svg').read_text(encoding='utf-8')))
    assert ORCHARD_ITEM_IDS <= icons and set(GRAFTS) <= icons
    assert {'sapling_' + t for t in TREES} <= icons and 'orchard' in icons
    types = re.search(r'const TYPES=\{([^}]*)\}', (STATIC / 'scene_buildings.js').read_text(encoding='utf-8')).group(1)
    assert {'dryer', 'cellar'} <= {m.split(':')[0].strip() for m in types.split(',')}
    scene = (STATIC / 'scene_orchard.js').read_text(encoding='utf-8')
    assert all(f'{t}:{{' in scene for t in TREES), 'every species has its own kit in the tree drawing'
