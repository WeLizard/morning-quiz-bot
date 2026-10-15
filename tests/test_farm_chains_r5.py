"""Farm catalog r5: second-circle production chains (six workshops, levels 10-23), orders, old-save compatibility."""
from copy import deepcopy
from pathlib import Path
import re
from uuid import uuid4

import pytest

from qw_farm.catalog import ANIMALS, BUILDINGS, ITEMS, LEVELS, R9_RECIPE_IDS, RECIPES, VERSION, validate
from qw_farm.domain import FarmError, apply, make_order, new_farm, reachable, validate_state
from qw_farm.expansion import upgrade_state

STATIC = Path(__file__).resolve().parents[1] / 'qw_farm' / 'static'
# building -> level at which it unlocks
NEW_BUILDINGS = {'oil_press': 10, 'juicery': 13, 'cannery': 14, 'smokehouse': 15, 'tailor': 17, 'confectionery': 19}
NEW_RECIPES = {k: r for k, r in RECIPES.items() if r['building'] in NEW_BUILDINGS and k not in R9_RECIPE_IDS}   # r9 adds its own rows to these workshops
NEW_ITEMS = {i for r in NEW_RECIPES.values() for i in r['outputs']}
# Luxury goods: the end of a chain, nothing in r5 consumes them.
LUXURY = {i for i in NEW_ITEMS if not any(i in r['inputs'] for r in NEW_RECIPES.values())}
# id: (building, level, seconds) of recipes that existed before r5: must never change.
OLD_RECIPES = {'flour': ('mill', 1, 60), 'bread': ('bakery', 2, 150), 'cheese': ('dairy', 4, 720), 'oil': ('mill', 5, 600),
               'linen': ('loom', 6, 1500), 'mint_tea': ('teahouse', 12, 480), 'sponge_cake': ('bakery', 10, 1500),
               'mohair_plaid': ('loom', 18, 2400), 'down_blanket': ('loom', 22, 2400), 'pickles': ('kitchen', 3, 600)}
OLD_BUILDINGS = {'mill': 1, 'bakery': 2, 'kitchen': 3, 'dairy': 4, 'loom': 5, 'teahouse': 3, 'swan_lake': 22}


def farm(xp, coins=10 ** 6):
    state = upgrade_state(new_farm(str(uuid4()), 'Chains', 1000))
    state.update(xp=xp, coins=coins, starter_credit=0)
    return state


def obj(kind, oid, animal=None):
    return dict(id=oid, type=kind, x=6, y=5, w=2, h=2, revision=0, level=1, jobs=[], animal=animal, animal_job=None)


def full_farm(level):
    """A farm of the given level that owns every building and every animal (what a late-game player has)."""
    state = farm(LEVELS[level - 1])
    for b in BUILDINGS:
        if not BUILDINGS[b]['decor']:
            state['objects'].append(obj(b, 'b_' + b))
    for a in ANIMALS.values():
        state['objects'].append(obj(a['building'], 'a_' + a['id'], a['id']))
    return state


def value(items):
    return sum(ITEMS[k]['price'] * q for k, q in items.items())


def per_hour(r):
    return (value(r['outputs']) - value(r['inputs'])) / (r['seconds'] / 3600)


def producer(item):
    return next((r for r in RECIPES.values() if item in r['outputs']), None)


def test_catalog_validates_version_and_old_rows_are_unchanged():
    validate()
    assert VERSION in {'farm-2026-10-r5', 'farm-2026-10-r6', 'farm-2026-10-r7', 'farm-2026-10-r8', 'farm-2026-10-r9'}
    for key, (building, lv, seconds) in OLD_RECIPES.items():
        r = RECIPES[key]
        assert (r['building'], r['level'], r['seconds']) == (building, lv, seconds), key
    for key, lv in OLD_BUILDINGS.items():
        assert BUILDINGS[key]['level'] == lv and not BUILDINGS[key]['decor']


def test_six_new_workshops_cover_levels_10_to_19_with_own_geometry():
    assert {k: BUILDINGS[k]['level'] for k in NEW_BUILDINGS} == NEW_BUILDINGS
    for key in NEW_BUILDINGS:
        b = BUILDINGS[key]
        assert not b['decor'] and (b['w'], b['h']) == (2, 2) and b['cost'] > 0
    costs = [BUILDINGS[k]['cost'] for k in sorted(NEW_BUILDINGS, key=NEW_BUILDINGS.get)]
    assert costs == sorted(costs)  # later workshops cost more
    assert 18 <= len(NEW_RECIPES) <= 24
    assert {r['building'] for r in NEW_RECIPES.values()} == set(NEW_BUILDINGS)  # no workshop stands empty


@pytest.mark.parametrize('building,lv', NEW_BUILDINGS.items())
def test_workshop_unlocks_at_its_level_and_runs_its_recipes(building, lv):
    low = farm(LEVELS[lv - 2])
    with pytest.raises(FarmError) as error:
        apply(low, low, 'build', dict(type=building, x=4, y=9), 1000, str(uuid4()))
    assert error.value.code == 'locked'
    state = farm(LEVELS[lv - 1])
    coins = state['coins']
    apply(state, state, 'build', dict(type=building, x=0, y=6), 1000, str(uuid4()))
    assert state['coins'] == coins - BUILDINGS[building]['cost']
    made = next(o for o in state['objects'] if o['type'] == building)
    first = min((r for r in NEW_RECIPES.values() if r['building'] == building), key=lambda r: r['level'])
    state['xp'] = LEVELS[max(first['level'], lv) - 1]
    state['inventory'].update({k: q for k, q in first['inputs'].items()})
    apply(state, state, 'queue', dict(object=made['id'], recipe=first['id']), 1000, 'job1')
    job = made['jobs'][0]
    apply(state, state, 'collect', dict(object=made['id'], job='job1'), job['ready_at'], str(uuid4()))
    assert all(state['inventory'].get(k, 0) == q for k, q in first['outputs'].items())


def test_recipe_is_locked_below_its_level():
    low = farm(LEVELS[21])  # level 22, the cake needs 23
    low['objects'].append(obj('confectionery', 'c1'))
    low['inventory'].update(saffron=2, butter=1, flour=2, egg=2)
    with pytest.raises(FarmError):
        apply(low, low, 'queue', dict(object='c1', recipe='saffron_cake'), 1000, 'j')
    low['xp'] = LEVELS[22]
    apply(low, low, 'queue', dict(object='c1', recipe='saffron_cake'), 1000, 'j')


def test_every_recipe_input_is_producible_at_or_below_its_level():
    for key, r in NEW_RECIPES.items():
        assert r['level'] >= BUILDINGS[r['building']]['level'], key
        state = full_farm(r['level'])
        missing = set(r['inputs']) - set(reachable(state))
        assert not missing, (key, missing)
        # ...and not available a level earlier only when the recipe's own gate is what blocks it
        for item in r['inputs']:
            made = producer(item)
            if made:
                assert made['level'] <= r['level'], (key, item)


def test_inputs_come_from_existing_items_and_new_items_have_prices():
    for key, r in NEW_RECIPES.items():
        assert set(r['inputs']) <= set(ITEMS)
        assert all(ITEMS[i]['kind'] == 'product' and ITEMS[i]['price'] > 0 for i in r['outputs'])
        assert set(r['outputs']) <= NEW_ITEMS
    # new crops from r3 and animal products from r4 are actually used
    used = {i for r in NEW_RECIPES.values() for i in r['inputs']}
    assert {'grape', 'melon', 'cranberry', 'saffron', 'poppy', 'eggplant', 'pepper'} <= used
    assert {'quail_egg', 'mohair', 'honey', 'sponge_cake', 'scarf'} <= used


def test_chains_are_complete_and_two_to_three_stages_deep():
    def depth(item, only_new):
        r = producer(item)
        if not r or (only_new and r['id'] not in NEW_RECIPES):
            return 0
        return 1 + max((depth(i, only_new) for i in r['inputs']), default=0)
    for item in NEW_ITEMS - LUXURY:  # every intermediate is consumed by a later stage
        assert any(item in r['inputs'] for r in NEW_RECIPES.values()), item
    assert len(LUXURY) >= 6
    inside = {i: depth(i, True) for i in LUXURY}      # stages inside the six new workshops
    overall = {i: depth(i, False) for i in LUXURY}    # including mill/dairy/loom/kitchen steps before them
    assert min(inside.values()) >= 1 and sum(d >= 2 for d in inside.values()) >= 6
    assert max(overall.values()) == 3 and min(overall.values()) >= 2
    # luxury goods are worth clearly more than any single raw input they need
    for item in LUXURY:
        r = producer(item)
        assert ITEMS[item]['price'] * r['outputs'][item] > max(ITEMS[i]['price'] for i in r['inputs'])


def test_depth_is_rewarded_but_balance_stays_in_the_old_class():
    old = [per_hour(r) for k, r in RECIPES.items() if k not in NEW_RECIPES and r['seconds'] >= 300]
    best_old = max(old)
    assert 380 <= best_old <= 400  # mint tea; if an old recipe moves, revisit this table
    first_stage = [per_hour(r) for r in NEW_RECIPES.values() if not any(producer(i) and producer(i)['id'] in NEW_RECIPES for i in r['inputs'])]
    luxury = [per_hour(producer(i)) for i in LUXURY]
    assert min(per_hour(r) for r in NEW_RECIPES.values()) >= 150
    assert max(per_hour(r) for r in NEW_RECIPES.values()) <= best_old * 1.5
    assert max(luxury) > max(first_stage) and sum(luxury) / len(luxury) > sum(first_stage) / len(first_stage)
    for r in NEW_RECIPES.values():
        assert r['xp'] / (r['seconds'] / 3600) <= 50  # same class as the existing ~40 xp per hour


def test_whole_chain_per_hour_does_not_explode():
    def expand(item, qty, acc):
        r = producer(item)
        if not r or r['id'] not in NEW_RECIPES:
            acc['raw'] += ITEMS[item]['price'] * qty
            return
        batches = qty / r['outputs'][item]
        acc['hours'] += batches * r['seconds'] / 3600
        for k, q in r['inputs'].items():
            expand(k, q * batches, acc)
    best_old = max(per_hour(r) for k, r in RECIPES.items() if k not in NEW_RECIPES and r['seconds'] >= 300)
    for item in LUXURY:
        r = producer(item)
        acc = dict(raw=0, hours=0)
        expand(item, r['outputs'][item], acc)
        chain = (ITEMS[item]['price'] * r['outputs'][item] - acc['raw']) / acc['hours']
        assert 200 <= chain <= best_old * 1.5, (item, chain)
        assert ITEMS[item]['price'] * r['outputs'][item] > acc['raw']


def test_orders_use_luxury_goods_only_from_their_level():
    seen = {9: set(), 24: set()}
    for tag in range(40):
        for lv in seen:
            state = full_farm(lv)
            state['id'] = f'order-chain-{tag}'
            state['order_seq'] = 3
            for slot in range(30):
                order = make_order(state, slot % 3, 1000)
                assert set(order['needs']) <= set(ITEMS)
                seen[lv].update(order['needs'])
    assert not seen[9] & NEW_ITEMS
    assert len(seen[24] & LUXURY) >= 4
    state = full_farm(24)
    assert LUXURY <= set(reachable(state))


def test_new_goods_are_reachable_only_with_their_workshop_and_level():
    for item in NEW_ITEMS:
        r = producer(item)
        lv = r['level']
        ok = full_farm(lv)
        assert item in reachable(ok), item
        low = full_farm(lv - 1)
        assert item not in reachable(low), item
        bare = full_farm(lv)
        bare['objects'] = [o for o in bare['objects'] if o['type'] != r['building']]
        assert item not in reachable(bare), item


def test_luxury_order_pays_a_big_reward():
    state = full_farm(24)
    rewards = []
    for tag in range(60):
        state['id'] = f'reward-{tag}'
        state['order_seq'] = 3
        for slot in range(3):
            order = make_order(state, slot, 1000)
            if set(order['needs']) & LUXURY:
                rewards.append(order['coins'])
    assert rewards and max(rewards) >= 700


def test_r4_save_loads_unchanged_and_new_workshop_works_in_it():
    old = new_farm(str(uuid4()), 'Legacy', 1000)
    old['catalog'] = 'farm-2026-10-r4'
    old['xp'] = LEVELS[11]
    old['objects'].append(dict(id='sw1', type='swan_lake', x=6, y=5, w=2, h=2, revision=0, level=1, jobs=[],
                               animal='swan', animal_job=dict(ready_at=1500, outputs={'swan_down': 2}, version='farm-2026-10-r4')))
    before = deepcopy(old)
    upgraded = upgrade_state(old)
    for key in ('id', 'coins', 'inventory', 'objects', 'orders', 'xp'):
        assert upgraded[key] == before[key]
    assert upgraded['catalog'] == VERSION
    validate_state(upgraded)
    apply(upgraded, upgraded, 'collect_animal', dict(object='sw1'), 1500, str(uuid4()))
    assert upgraded['inventory']['swan_down'] == 2
    upgraded['coins'] = 10 ** 6
    apply(upgraded, upgraded, 'build', dict(type='oil_press', x=0, y=6), 1500, str(uuid4()))


def test_frontend_assets_cover_every_new_id():
    icons = set(re.findall(r'<symbol id="([a-z_0-9]+)"', (STATIC / 'icons.svg').read_text(encoding='utf-8')))
    buildings = (STATIC / 'scene_buildings.js').read_text(encoding='utf-8')
    types = re.search(r'const TYPES=\{([^}]*)\}', buildings).group(1)
    drawers = {m.split(':')[0].strip() for m in types.split(',')}
    for item in NEW_ITEMS:
        assert item in icons, item
    for building in NEW_BUILDINGS:
        assert building in drawers, building
