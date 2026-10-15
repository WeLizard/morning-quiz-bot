"""Farm catalog r4: second-circle livestock (levels 8-22), feed->product cycle, recipes, orders, old-save compatibility."""
from copy import deepcopy
from pathlib import Path
import re
from uuid import uuid4

import pytest

from qw_farm.catalog import ANIMALS, BUILDINGS, ITEMS, LEVELS, RECIPES, VERSION, validate
from qw_farm.domain import FarmError, apply, make_order, new_farm, reachable, validate_state
from qw_farm.expansion import upgrade_state

STATIC = Path(__file__).resolve().parents[1] / 'qw_farm' / 'static'
# animal -> (building, level)
NEW = {'pig': ('pigsty', 8), 'turkey': ('turkey_yard', 10), 'quail': ('quail_house', 12),
       'peacock': ('peacock_aviary', 15), 'angora': ('angora_pen', 18), 'swan': ('swan_lake', 22)}
NEW_RECIPES = ['gingerbread', 'truffle_tart', 'truffle_soup', 'omelet', 'sponge_cake', 'quail_salad',
               'feather_fan', 'plume_bouquet', 'mittens', 'mohair_plaid', 'down_blanket']
# building, level, cost, seconds of every animal that existed before r4: must never change.
OLD_ANIMALS = {'chicken': ('coop', 1, 65, 240), 'cow': ('cowshed', 4, 180, 900), 'sheep': ('sheepfold', 5, 200, 1200),
               'bees': ('apiary', 7, 220, 1800), 'duck': ('duckpond', 3, 120, 600), 'goat': ('goatshed', 4, 180, 1500),
               'rabbit': ('rabbit_hutch', 3, 130, 1800), 'alpaca': ('alpaca_pen', 7, 280, 3600),
               'goose': ('goose_house', 4, 150, 1200)}
NEW_PRODUCTS = {i for a in NEW for i in ANIMALS[a]['outputs']}


def farm(xp, coins=10 ** 6):
    state = upgrade_state(new_farm(str(uuid4()), 'Animals', 1000))
    state.update(xp=xp, coins=coins, starter_credit=0)
    return state


def house(state, kind, oid='h1', animal=None):
    obj = dict(id=oid, type=kind, x=6, y=5, w=2, h=2, revision=0, level=1, jobs=[], animal=animal, animal_job=None)
    state['objects'].append(obj)
    return obj


def test_catalog_validates_and_old_animals_are_unchanged():
    validate()
    assert VERSION in {'farm-2026-10-r4', 'farm-2026-10-r5', 'farm-2026-10-r6', 'farm-2026-10-r7', 'farm-2026-10-r8', 'farm-2026-10-r9'}
    for key, (building, lv, cost, seconds) in OLD_ANIMALS.items():
        a = ANIMALS[key]
        assert (a['building'], a['level'], a['cost'], a['seconds']) == (building, lv, cost, seconds), key


def test_new_animals_cover_levels_8_to_22_with_own_buildings():
    assert {k: (ANIMALS[k]['building'], ANIMALS[k]['level']) for k in NEW} == NEW
    for building, lv in NEW.values():
        b = BUILDINGS[building]
        assert not b['decor'] and b['level'] == lv and (b['w'], b['h']) == (2, 2)
    assert len({a['building'] for a in ANIMALS.values()}) == len(ANIMALS)  # one house per species


@pytest.mark.parametrize('key', NEW)
def test_animal_unlocks_at_its_level_and_runs_feed_to_product_cycle(key):
    building, lv = NEW[key]
    spec = ANIMALS[key]
    low = farm(LEVELS[lv - 2])
    with pytest.raises(FarmError) as error:
        apply(low, low, 'build', dict(type=building, x=4, y=9), 1000, str(uuid4()))
    assert error.value.code == 'locked'
    state = farm(LEVELS[lv - 1])
    obj = house(state, building)
    coins = state['coins']
    apply(state, state, 'buy_animal', dict(object='h1', animal=key), 1000, str(uuid4()))
    assert state['coins'] == coins - spec['cost'] and obj['animal'] == key
    with pytest.raises(FarmError):  # nothing to feed with yet
        apply(state, state, 'feed', dict(object='h1'), 1000, str(uuid4()))
    state['inventory'].update({k: 3 for k in spec['inputs']})
    apply(state, state, 'feed', dict(object='h1'), 1000, str(uuid4()))
    assert all(state['inventory'][k] == 3 - q for k, q in spec['inputs'].items())
    ready = obj['animal_job']['ready_at']
    assert 1000 < ready <= 1000 + spec['seconds']
    with pytest.raises(FarmError):
        apply(state, state, 'collect_animal', dict(object='h1'), ready - 1, str(uuid4()))
    apply(state, state, 'collect_animal', dict(object='h1'), ready, str(uuid4()))
    assert all(state['inventory'][k] == q for k, q in spec['outputs'].items())


def test_animal_cannot_live_in_a_foreign_house():
    state = farm(LEVELS[21])
    obj = house(state, 'pigsty')
    with pytest.raises(FarmError):
        apply(state, state, 'buy_animal', dict(object='h1', animal='swan'), 1000, str(uuid4()))


def test_feed_comes_from_existing_items_and_outputs_are_new_products():
    for key in NEW:
        assert set(ANIMALS[key]['inputs']) <= set(ITEMS) - NEW_PRODUCTS
        for item in ANIMALS[key]['outputs']:
            assert ITEMS[item]['kind'] == 'product'


def test_balance_is_in_the_class_of_existing_animals():
    def gain(a):
        return sum(ITEMS[k]['price'] * q for k, q in a['outputs'].items()) - sum(ITEMS[k]['price'] * q for k, q in a['inputs'].items())

    def per_hour(a):
        return gain(a) / (a['seconds'] / 3600)
    old = [per_hour(ANIMALS[k]) for k in OLD_ANIMALS]
    for key in NEW:
        p = per_hour(ANIMALS[key])
        assert 90 <= p <= 135 and p <= max(old), (key, p)
        assert ANIMALS[key]['cost'] / p <= 15  # pays back in well under a day of attention-free waiting
    by_level = sorted(NEW, key=lambda a: NEW[a][1])
    assert gain(ANIMALS[by_level[-1]]) > gain(ANIMALS[by_level[0]])


def test_new_recipes_use_existing_items_and_buildings_and_add_value():
    validate()
    used = set()
    for key in NEW_RECIPES:
        r = RECIPES[key]
        assert r['building'] in BUILDINGS and set(r['inputs']) | set(r['outputs']) <= set(ITEMS)
        assert 6 <= r['level'] <= 22
        used |= set(r['inputs']) & NEW_PRODUCTS
    assert used == NEW_PRODUCTS  # every new product has a use


def test_honey_chain_is_complete():
    users = {k for k, r in RECIPES.items() if 'honey' in r['inputs']}
    assert {'honeybun', 'mint_tea', 'gingerbread', 'sponge_cake'} <= users
    assert ANIMALS['bees']['outputs'] == {'honey': 2}


def test_recipe_runs_in_its_building():
    state = farm(LEVELS[17])
    loom = dict(id='l1', type='loom', x=6, y=5, w=2, h=2, revision=0, level=1, jobs=[], animal=None, animal_job=None)
    state['objects'].append(loom)
    state['inventory'].update(mohair=3)
    apply(state, state, 'queue', dict(object='l1', recipe='mohair_plaid'), 1000, 'job1')
    job = loom['jobs'][0]
    apply(state, state, 'collect', dict(object='l1', job='job1'), job['ready_at'], str(uuid4()))
    assert state['inventory']['mohair_plaid'] == 1 and not state['inventory'].get('mohair')


def test_orders_use_new_products_only_from_their_level():
    seen = {7: set(), 22: set()}
    for tag in range(30):
        for lv in seen:
            state = farm(LEVELS[lv - 1])
            for animal, (building, _) in NEW.items():
                house(state, building, 'x' + building, animal)
            state['id'] = f'order-farm-{tag}'
            state['order_seq'] = 3
            for slot in range(30):
                order = make_order(state, slot % 3, 1000)
                assert set(order['needs']) <= set(ITEMS)
                seen[lv].update(order['needs'])
    assert not seen[7] & NEW_PRODUCTS
    assert len(seen[22] & NEW_PRODUCTS) >= 3


def test_animal_product_is_reachable_only_from_the_animal_level():
    for key, (building, lv) in NEW.items():
        item = next(iter(ANIMALS[key]['outputs']))
        low = farm(LEVELS[lv - 2])
        house(low, building, 'h', key)
        ok = farm(LEVELS[lv - 1])
        house(ok, building, 'h', key)
        assert item not in reachable(low)
        # the feed crops of the top-level animals are only reachable if that level also grows them
        if set(ANIMALS[key]['inputs']) <= set(reachable(ok)):
            assert item in reachable(ok)


def test_r3_save_loads_unchanged_and_still_works():
    old = new_farm(str(uuid4()), 'Legacy', 1000)
    old['catalog'] = 'farm-2026-10-r3'
    old['xp'] = LEVELS[9]
    old['objects'].append(dict(id='cow1', type='cowshed', x=6, y=5, w=2, h=2, revision=0, level=1, jobs=[],
                               animal='cow', animal_job=dict(ready_at=1500, outputs={'milk': 2}, version='farm-2026-10-r3')))
    before = deepcopy(old)
    upgraded = upgrade_state(old)
    for key in ('id', 'coins', 'inventory', 'objects', 'orders', 'xp'):
        assert upgraded[key] == before[key]
    assert upgraded['catalog'] == VERSION
    validate_state(upgraded)
    apply(upgraded, upgraded, 'collect_animal', dict(object='cow1'), 1500, str(uuid4()))
    assert upgraded['inventory']['milk'] == 2


def test_frontend_assets_cover_every_new_id():
    icons = set(re.findall(r'<symbol id="([a-z_0-9]+)"', (STATIC / 'icons.svg').read_text(encoding='utf-8')))
    buildings = (STATIC / 'scene_buildings.js').read_text(encoding='utf-8')
    sprites = (STATIC / 'scene_expansion.js').read_text(encoding='utf-8')
    types = re.search(r'const TYPES=\{([^}]*)\}', buildings).group(1)
    drawers = {m.split(':')[0].strip() for m in types.split(',')}
    for key in NEW_PRODUCTS | set(NEW_RECIPES):
        assert key in icons, key
    for animal, (building, _) in NEW.items():
        assert building in drawers, building
        assert f"id==='{animal}'" in sprites, animal
    for building, *_ in OLD_ANIMALS.values():
        assert building in drawers or building == 'duckpond'
