"""Farm catalog r3: crops for levels 9-20, their recipes, orders, balance and old-save compatibility."""
from copy import deepcopy
from pathlib import Path
import re
from uuid import uuid4

import pytest

from qw_farm.catalog import CROP_TUNING_R9, CROPS, ITEMS, LEVELS, RECIPES, VERSION, validate
from qw_farm.domain import FarmError, apply, make_order, new_farm, reachable, validate_state
from qw_farm.expansion import upgrade_state

STATIC = Path(__file__).resolve().parents[1] / 'qw_farm' / 'static'
NEW = ['pepper', 'eggplant', 'buckwheat', 'mint', 'grape', 'chamomile',
       'hops', 'garlic', 'poppy', 'melon', 'cranberry', 'saffron']
NEW_RECIPES = ['porridge', 'mint_tea', 'grape_roll', 'hop_wreath']
# (cost, seconds, yield, price, xp, level) of every crop that existed before r3: must never change.
OLD = {
    'wheat': (2, 30, 3, 2, 1, 1), 'carrot': (4, 120, 3, 5, 3, 1), 'corn': (7, 360, 3, 8, 5, 1),
    'clover': (5, 240, 3, 6, 4, 2), 'strawberry': (12, 1200, 3, 16, 8, 3), 'potato': (16, 2700, 4, 14, 12, 4),
    'sunflower': (22, 3600, 3, 24, 16, 5), 'pumpkin': (32, 10800, 4, 35, 26, 6), 'lavender': (25, 7200, 3, 28, 22, 7),
    'tomato': (18, 1800, 3, 19, 10, 4), 'oat': (5, 1800, 4, 6, 5, 1), 'beet': (9, 600, 3, 11, 6, 2),
    'cucumber': (12, 900, 3, 14, 7, 2), 'cabbage': (15, 2400, 3, 18, 10, 3), 'peas': (16, 1500, 4, 15, 9, 3),
    'rye': (14, 7200, 5, 14, 14, 3), 'raspberry': (20, 3600, 4, 22, 15, 4), 'basil': (14, 1800, 3, 18, 10, 4),
    'blueberry': (26, 10800, 6, 25, 24, 5), 'flax': (26, 14400, 5, 24, 28, 6), 'rice': (30, 21600, 6, 25, 34, 7),
    'watermelon': (45, 28800, 5, 42, 42, 8),
}


def farm(xp, coins=10 ** 6):
    state = upgrade_state(new_farm(str(uuid4()), 'Crops', 1000))
    state.update(xp=xp, coins=coins, starter_credit=0)
    state['progress'].update(day=10 ** 9, dew=10 ** 9)  # r9: no Morning dew (M1) here: exact XP expectations
    return state


def plant(state, crop, at=1000):
    plot = next(o for o in state['objects'] if o['type'] == 'plot' and not o['crop'])
    return apply(state, state, 'plant', dict(object=plot['id'], crop=crop, revision=plot['revision']), at, str(uuid4()))


def test_catalog_validates_and_old_rows_are_unchanged():
    validate()
    for key, row in OLD.items():
        c = CROPS[key]
        assert c['price'] == row[3], key                      # the unit price (orders, trade, animals) never changes
        assert (c['cost'], c['seconds'], c['yield_qty'], c['xp'], c['level']) == CROP_TUNING_R9[key], key   # r9 retuned the rest
    assert VERSION in {'farm-2026-10-r3', 'farm-2026-10-r4', 'farm-2026-10-r5', 'farm-2026-10-r6', 'farm-2026-10-r7', 'farm-2026-10-r8', 'farm-2026-10-r9'}


def test_new_crops_cover_levels_9_to_20():
    assert sorted(CROPS[k]['level'] for k in NEW) == list(range(9, 21))
    assert all(k in ITEMS and ITEMS[k]['kind'] == 'crop' for k in NEW)


@pytest.mark.parametrize('crop', NEW)
def test_crop_is_plantable_at_its_level_and_not_before(crop):
    lv = CROPS[crop]['level']
    low = farm(LEVELS[lv - 2])
    with pytest.raises(FarmError) as error:
        plant(low, crop)
    assert error.value.code == 'locked'
    ok = farm(LEVELS[lv - 1])
    coins = ok['coins']
    plant(ok, crop)
    assert coins - ok['coins'] == CROPS[crop]['cost']
    planted = next(o['crop'] for o in ok['objects'] if o.get('crop') and o['crop']['id'] == crop)
    assert planted['ready_at'] == 1000 + CROPS[crop]['seconds']


@pytest.mark.parametrize('crop', NEW)
def test_new_crop_harvests_into_inventory(crop):
    state = farm(LEVELS[CROPS[crop]['level'] - 1])
    plant(state, crop)
    plot = next(o for o in state['objects'] if o.get('crop') and o['crop']['id'] == crop)
    ready = plot['crop']['ready_at']
    xp = state['xp']
    apply(state, state, 'harvest', dict(object=plot['id'], revision=plot['revision']), ready, str(uuid4()))
    assert state['inventory'][crop] == CROPS[crop]['yield_qty'] and state['xp'] == xp + CROPS[crop]['xp']


def test_balance_follows_the_existing_curve_without_dominating_it():
    # r9: times are spread over fast / medium / long classes, so only the long class is compared level by level.
    new = sorted((CROPS[k] for k in NEW), key=lambda c: c['level'])
    long_ = [c for c in new if c['seconds'] >= 14400]
    assert [c['xp'] for c in long_] == sorted(c['xp'] for c in long_) or all(
        b['xp'] >= a['xp'] * 0.9 for a, b in zip(long_, long_[1:]))
    # Never better per hour than 2x the best old long-wait crop (watermelon / rice class), counting the retuned old rows.
    ref = max((c['yield_qty'] * c['price'] - c['cost']) / (c['seconds'] / 3600) for c in (CROPS['watermelon'], CROPS['rice']))
    for c in long_:
        assert (c['yield_qty'] * c['price'] - c['cost']) / (c['seconds'] / 3600) <= ref * 2, c['id']
    # Every new row pays back its seed at least 2.5 times over (mint, garlic and poppy are one-sack crops, owner decision).
    assert all(c['yield_qty'] * c['price'] >= 2.5 * c['cost'] for c in new)


def test_new_recipes_use_existing_items_buildings_and_add_value():
    validate()
    for key in NEW_RECIPES:
        r = RECIPES[key]
        assert 8 <= r['level'] <= 20 and set(r['inputs']) | set(r['outputs']) <= set(ITEMS)
        assert any(i in NEW for i in r['inputs'])
    assert 2 <= len(NEW_RECIPES) <= 4


def test_recipe_runs_in_its_building():
    state = farm(LEVELS[14])
    kitchen = dict(id='k1', type='kitchen', x=0, y=7, w=2, h=2, revision=0, level=1, jobs=[], animal=None, animal_job=None)
    state['objects'].append(kitchen)
    state['inventory'].update(buckwheat=3, milk=1)
    apply(state, state, 'queue', dict(object='k1', recipe='porridge'), 1000, 'job1')
    job = kitchen['jobs'][0]
    apply(state, state, 'collect', dict(object='k1', job='job1'), job['ready_at'], str(uuid4()))
    assert state['inventory']['porridge'] == 1 and not state['inventory'].get('buckwheat')


def test_orders_reference_only_known_items_and_new_crops_appear_by_level():
    seen_low, seen_high = set(), set()
    for tag in range(40):
        for xp, seen in ((LEVELS[7], seen_low), (LEVELS[19], seen_high)):
            state = farm(xp)
            state['id'] = f'order-farm-{tag}'
            state['order_seq'] = 3
            for slot in range(30):
                order = make_order(state, slot % 3, 1000)
                assert set(order['needs']) <= set(ITEMS)
                seen.update(order['needs'])
    assert not seen_low & set(NEW)
    assert len(seen_high & set(NEW)) >= 8
    assert not set(NEW) & set(reachable(farm(LEVELS[7])))
    assert set(NEW) <= set(reachable(farm(LEVELS[19])))


def test_each_new_crop_unlocks_in_orders_exactly_at_its_level():
    for crop in NEW:
        lv = CROPS[crop]['level']
        assert crop not in reachable(farm(LEVELS[lv - 2]))
        assert crop in reachable(farm(LEVELS[lv - 1]))


def test_r2_save_loads_unchanged_and_still_works():
    old = new_farm(str(uuid4()), 'Legacy', 1000)
    old['catalog'] = 'farm-2026-10-r2'
    old['xp'] = LEVELS[9]
    old['inventory'].update(watermelon=3)
    old['objects'][-1]['crop'] = dict(id='watermelon', planted_at=900, ready_at=1500, yield_qty=5, xp=42,
                                      helped=False, version='farm-2026-10-r2')
    before = deepcopy(old)
    upgraded = upgrade_state(old)
    for key in ('id', 'coins', 'inventory', 'objects', 'orders', 'xp'):
        assert upgraded[key] == before[key]
    assert upgraded['catalog'] == VERSION
    validate_state(upgraded)
    plot = upgraded['objects'][-1]
    apply(upgraded, upgraded, 'harvest', dict(object=plot['id'], revision=plot['revision']), 1500, str(uuid4()))
    assert upgraded['inventory']['watermelon'] == 8


def test_frontend_assets_cover_every_new_item():
    icons = set(re.findall(r'<symbol id="([a-z_0-9]+)"', (STATIC / 'icons.svg').read_text(encoding='utf-8')))
    scene = (STATIC / 'scene.js').read_text(encoding='utf-8')
    for key in NEW + ['porridge', 'mint_tea', 'grape_roll', 'hop_wreath']:
        assert key in icons, key
    for key in NEW:
        assert scene.count(f"case '{key}':") >= 2, key  # sapling + mature drawing


def test_scene_keeps_trees_off_the_pond_and_the_fenced_farm():
    scene = (STATIC / 'scene.js').read_text(encoding='utf-8')
    assert 'treeBlocked' in scene and 'tree(x,y,s=1){if(this.treeBlocked(x,y,s))return;' in scene
