"""Farm catalog r9: crop times on a grid, classes per level band, the value law, recipe rules, price snapshot, old-save compatibility
and the new buildings / animal / recipes (docs/tasks/FARM_CROPS_R9_DESIGN.md)."""
from uuid import uuid4

import pytest

from qw_farm import catalog, progression, undo
from qw_farm.catalog import (ANIMALS, BUILDINGS, CROP_TUNING_R9, CROPS, ITEMS, LEVELS, R9_ITEM_IDS, R9_RECIPE_IDS, RECIPES, VERSION,
                             crop_class, validate)
from qw_farm.domain import apply, new_farm, reachable, validate_state
from qw_farm.expansion import upgrade_state

# Unit prices of every item that existed in r8: they must never change (orders, caravan, contracts, animals, stock).
R8_PRICES = {'wheat': 2, 'carrot': 5, 'corn': 8, 'clover': 6, 'strawberry': 16, 'potato': 14, 'sunflower': 24, 'pumpkin': 35, 'lavender': 28, 'tomato': 19, 'flour': 10, 'feed': 8, 'hay': 12, 'egg': 11, 'milk': 18, 'wool': 25, 'honey': 46, 'bread': 29, 'bun': 39, 'jam': 53, 'cheese': 53, 'oil': 64, 'soup': 57, 'pie': 175, 'yarn': 67, 'bouquet': 99, 'pancake': 69, 'salad': 70, 'oat': 6, 'beet': 11, 'cucumber': 14, 'cabbage': 18, 'peas': 15, 'rye': 14, 'raspberry': 22, 'basil': 18, 'blueberry': 25, 'flax': 24, 'rice': 25, 'watermelon': 42, 'mushroom': 18, 'chanterelle': 23, 'wildberry': 17, 'blackberry': 24, 'herbs': 14, 'hazelnut': 21, 'duck_egg': 14, 'goat_milk': 24, 'rabbit_fluff': 28, 'alpaca_fiber': 36, 'feather': 22, 'mushroom_soup': 83, 'berry_jam': 66, 'tea': 53, 'pickles': 58, 'goat_cheese': 72, 'linen': 94, 'forest_pie': 96, 'oat_cookie': 65, 'pillow': 100, 'scarf': 96, 'vegetable_stew': 132, 'berry_milk': 117, 'rice_pudding': 125, 'pepper': 48, 'eggplant': 55, 'buckwheat': 46, 'mint': 66, 'grape': 72, 'chamomile': 64, 'hops': 86, 'garlic': 74, 'poppy': 86, 'melon': 116, 'cranberry': 104, 'saffron': 140, 'porridge': 205, 'mint_tea': 230, 'grape_roll': 230, 'hop_wreath': 340, 'truffle': 60, 'turkey_egg': 38, 'quail_egg': 24, 'peacock_feather': 66, 'mohair': 108, 'swan_down': 130, 'truffle_tart': 150, 'truffle_soup': 170, 'omelet': 230, 'sponge_cake': 230, 'quail_salad': 215, 'feather_fan': 280, 'plume_bouquet': 330, 'mittens': 190, 'mohair_plaid': 460, 'down_blanket': 700, 'gingerbread': 110, 'butter': 57, 'nut_paste': 197, 'poppy_oil': 341, 'grape_juice': 91, 'melon_nectar': 169, 'cranberry_morse': 209, 'ajvar': 155, 'marinated_mushrooms': 92, 'preserves_set': 513, 'smoked_cheese': 95, 'smoked_quail': 72, 'smoke_platter': 546, 'dyed_linen': 252, 'sundress': 746, 'alpaca_coat': 881, 'croissant': 49, 'grape_jelly': 157, 'poppy_roll': 294, 'praline_cake': 934, 'pastila': 279, 'saffron_cake': 702}
GRID = {30, 120, 300, 900, 1800, 3600, 7200, 14400, 28800, 43200, 86400}
K = {30: .091, 120: .183, 300: .289, 900: .5, 1800: .707, 3600: 1, 7200: 1.414, 14400: 2, 28800: 2.83, 43200: 3.3, 86400: 4.0}
STARTERS = {'wheat', 'carrot', 'corn', 'clover'}       # the first minutes of the game are not on the law
BANDS = {
    (1, 4): dict(fast={'wheat', 'carrot', 'corn', 'clover', 'beet', 'strawberry', 'basil'},
                 medium={'oat', 'cucumber', 'peas', 'tomato', 'rye', 'potato', 'raspberry'}, long={'cabbage'}),
    (5, 8): dict(fast={'lavender'}, medium={'sunflower', 'blueberry', 'pumpkin'}, long={'flax', 'rice', 'watermelon'}),
    (9, 12): dict(fast={'mint'}, medium={'pepper'}, long={'eggplant', 'buckwheat'}),
    (13, 16): dict(fast={'garlic'}, medium={'grape'}, long={'chamomile', 'hops'}),
    (17, 20): dict(fast={'poppy'}, medium={'melon', 'cranberry'}, long={'saffron'}),
}


def farm(xp, coins=10 ** 6):
    state = upgrade_state(new_farm(str(uuid4()), 'R9', 1000))
    state.update(xp=xp, coins=coins, starter_credit=0)
    state['progress'].update(day=10 ** 9, dew=10 ** 9)
    return state


def obj(kind, oid, animal=None):
    return dict(id=oid, type=kind, x=6, y=5, w=2, h=2, revision=0, level=1, jobs=[], animal=animal, animal_job=None)


def test_catalog_validates_and_is_versioned():
    validate()
    assert VERSION == 'farm-2026-10-r9'
    assert set(CROP_TUNING_R9) == set(CROPS)


def test_every_crop_time_is_on_the_grid_and_matches_the_tuning_table():
    for key, c in CROPS.items():
        assert c['seconds'] in GRID, key
        assert (c['cost'], c['seconds'], c['yield_qty'], c['xp'], c['level']) == CROP_TUNING_R9[key]


@pytest.mark.parametrize('band', BANDS)
def test_every_band_has_all_three_classes_as_designed(band):
    lo, hi = band
    found = {'fast': set(), 'medium': set(), 'long': set()}
    for key, c in CROPS.items():
        if lo <= c['level'] <= hi:
            found[crop_class(c['seconds'])].add(key)
    assert found == BANDS[band]


def test_the_value_law_holds_within_12_percent_except_the_starters():
    for key, c in CROPS.items():
        if key in STARTERS:
            continue
        law = 11 * 1.055 ** (c['level'] - 1) * K[c['seconds']]
        assert abs(c['xp'] / law - 1) <= .12, (key, c['xp'], law)
        profit = c['yield_qty'] * c['price'] - c['cost']
        assert 3.6 <= profit / c['xp'] <= 4.4, key                  # profit ~ 4 x XP


def test_same_time_means_a_better_newer_crop_r2():
    by_time = {}
    for c in CROPS.values():
        by_time.setdefault(c['seconds'], []).append(c)
    for seconds, group in by_time.items():
        group.sort(key=lambda c: c['level'])
        for a, b in zip(group, group[1:]):
            assert b['xp'] >= a['xp'] and b['yield_qty'] * b['price'] - b['cost'] >= a['yield_qty'] * a['price'] - a['cost'], (a['id'], b['id'])


def test_field_crops_are_exactly_the_long_class():
    assert {k for k, c in CROPS.items() if c['field']} == {k for k, c in CROPS.items() if crop_class(c['seconds']) == 'long'}
    assert sorted(k for k, c in CROPS.items() if c['field']) == sorted(
        ['cabbage', 'flax', 'rice', 'watermelon', 'eggplant', 'buckwheat', 'chamomile', 'hops', 'saffron'])
    assert all(c['seconds'] >= catalog.FIELD_MIN_GROW for c in CROPS.values() if c['field'])


def test_item_prices_of_existing_goods_did_not_change():
    for key, price in R8_PRICES.items():
        assert ITEMS[key]['price'] == price, key
    assert set(ITEMS) - set(R8_PRICES) == R9_ITEM_IDS


def test_ingredient_rule_for_r9_and_corrected_recipes():
    ids = set(R9_RECIPE_IDS) | {'linen', 'rice_pudding', 'hop_wreath'}
    for rid in ids:
        for item, qty in RECIPES[rid]['inputs'].items():
            c = CROPS.get(item)
            if not c:
                continue
            cls = crop_class(c['seconds'])
            if cls == 'fast':
                assert qty <= 3 * c['yield_qty'], (rid, item)
            elif cls == 'medium':
                assert qty <= 2 * c['yield_qty'], (rid, item)
            else:
                assert qty <= c['yield_qty'] / 2, (rid, item)
    assert RECIPES['linen']['inputs'] == {'flax': 2} and RECIPES['rice_pudding']['inputs'] == {'rice': 2, 'milk': 1}
    assert RECIPES['hop_wreath']['inputs'] == {'hops': 2} and RECIPES['hop_wreath']['seconds'] == 1800


def test_new_recipes_are_valid_priced_by_the_formula_and_at_least_two_minutes():
    for rid in R9_RECIPE_IDS:
        r = RECIPES[rid]
        assert r['seconds'] >= 120 and r['building'] in BUILDINGS and r['xp'] >= 1
        assert set(r['inputs']) | set(r['outputs']) <= set(ITEMS)
        out = sum(ITEMS[k]['price'] * q for k, q in r['outputs'].items())
        inp = sum(ITEMS[k]['price'] * q for k, q in r['inputs'].items())
        assert out >= inp
        # price = (inputs + added value) / output, added value = minutes x (2.5 + 0.1 L); rounding is allowed for
        added = r['seconds'] / 60 * (2.5 + .1 * r['level'])
        assert abs(out - (inp + added)) <= 2 + len(r['outputs']) * 2, rid


def test_chains_of_new_recipes_are_closed_and_without_duplicates():
    producers = {}
    for rid in R9_RECIPE_IDS:
        for item in RECIPES[rid]['outputs']:
            producers.setdefault(item, []).append(rid)
    assert all(len(v) == 1 for v in producers.values())             # no item is made twice
    others = {i for r in RECIPES.values() for i in r['outputs']} | {i for a in ANIMALS.values() for i in a['outputs']}
    makeable = others | set(CROPS) | {i for i, v in ITEMS.items() if v['kind'] == 'forest'}
    for rid in R9_RECIPE_IDS:
        assert set(RECIPES[rid]['inputs']) <= makeable, rid
    assert 'meat' in makeable and 'whey' in makeable


def test_early_dairy_in_the_dairy_and_hard_dairy_in_the_creamery():
    assert RECIPES['kefir']['building'] == RECIPES['curd']['building'] == 'dairy' and RECIPES['kefir']['level'] == RECIPES['curd']['level'] == 6
    assert RECIPES['curd']['outputs'] == {'curd': 1, 'whey': 2}
    for rid in ('yogurt', 'ryazhenka', 'smetana', 'whey_drink'):
        assert RECIPES[rid]['building'] == 'creamery' and RECIPES[rid]['level'] >= BUILDINGS['creamery']['level']
    assert BUILDINGS['creamery']['level'] == 21 and RECIPES['syrniki']['building'] == 'kitchen'
    assert RECIPES['brynza']['building'] == RECIPES['aged_cheese']['building'] == 'dairy'


def test_cattle_barn_calves_and_the_sausage_shop():
    assert BUILDINGS['cattle_barn']['level'] == 25 and BUILDINGS['sausage_shop']['level'] == 26
    assert BUILDINGS['cattle_barn']['name'] == 'Хлев' and not BUILDINGS['cattle_barn']['decor']
    calf = ANIMALS['calf']
    assert calf['building'] == 'cattle_barn' and calf['outputs'] == {'meat': 2} and calf['level'] >= BUILDINGS['cattle_barn']['level']
    assert all(RECIPES[r]['building'] == 'sausage_shop' for r in ('mince', 'sausages', 'mushroom_cutlets', 'doctor_sausage', 'dumplings', 'cutlets'))
    assert 'meat' not in {k for r in RECIPES.values() for k in r['outputs']}          # no «farm meat from feed» recipe: meat comes from calves
    assert RECIPES['servelat']['building'] == 'smokehouse' and RECIPES['cabbage_rolls']['building'] == 'kitchen'
    assert RECIPES['kulebyaka']['building'] == 'bakery'
    text = ' '.join(str(v) for d in (BUILDINGS['cattle_barn'], ANIMALS['calf'], ITEMS['meat']) for v in d.values()).lower()
    assert 'забо' not in text


def test_calf_batch_runs_through_the_ordinary_animal_commands():
    state = farm(LEVELS[ANIMALS['calf']['level'] - 1])
    apply(state, state, 'build', dict(type='cattle_barn', x=0, y=6), 1000, str(uuid4()))
    barn = next(o for o in state['objects'] if o['type'] == 'cattle_barn')
    apply(state, state, 'buy_animal', dict(object=barn['id'], animal='calf'), 1000, str(uuid4()))
    state['inventory'].update(ANIMALS['calf']['inputs'])
    apply(state, state, 'feed', dict(object=barn['id']), 1000, str(uuid4()))
    xp = state['xp']
    apply(state, state, 'collect_animal', dict(object=barn['id']), barn['animal_job']['ready_at'], str(uuid4()))
    assert state['inventory']['meat'] == 2 and state['xp'] > xp
    validate_state(state)


def test_new_recipes_run_in_their_workshops():
    for rid in sorted(R9_RECIPE_IDS):
        r = RECIPES[rid]
        need_lv = max(r['level'], BUILDINGS[r['building']]['level'])
        state = farm(LEVELS[need_lv - 1])
        state['objects'].append(obj(r['building'], 'w1'))
        state['inventory'].update(r['inputs'])
        apply(state, state, 'queue', dict(object='w1', recipe=rid), 1000, 'job-' + rid)
        job = state['objects'][-1]['jobs'][0]
        apply(state, state, 'collect', dict(object='w1', job=job['id']), job['ready_at'], str(uuid4()))
        assert all(state['inventory'].get(k, 0) >= q for k, q in r['outputs'].items()), rid


def test_new_goods_are_reachable_for_orders_with_their_building_and_level():
    for rid in ('kefir', 'yogurt', 'mince', 'servelat', 'kulebyaka', 'borscht'):
        r = RECIPES[rid]
        lv = max(r['level'], BUILDINGS[r['building']]['level'])
        full = farm(LEVELS[lv - 1])
        for b, spec in BUILDINGS.items():
            if not spec['decor'] and spec['level'] <= lv:
                full['objects'].append(obj(b, 'b_' + b))
        for a in ANIMALS.values():
            if a['level'] <= lv:
                full['objects'].append(obj(a['building'], 'a_' + a['id'], a['id']))
        assert next(iter(r['outputs'])) in reachable(full), rid


def test_old_plantings_jobs_and_batches_finish_by_their_old_parameters():
    state = farm(LEVELS[9])
    state['size'] = 20
    # an r8 cabbage (40 minutes, 3 pieces, xp 10) and an r8 beet planted before the update
    for i, (crop, qty, xp, secs) in enumerate((('cabbage', 3, 10, 2400), ('beet', 3, 6, 600))):
        state['objects'].append(dict(id=f'old{i}', type='plot', x=i, y=18, w=1, h=1, revision=0,
                                     crop=dict(id=crop, planted_at=0, ready_at=secs, yield_qty=qty, xp=xp, helped=False, watered=False,
                                               version='farm-2026-10-r8')))
    xp = state['xp']
    apply(state, state, 'harvest', dict(object='old0', revision=0), 2400, str(uuid4()))
    assert state['inventory']['cabbage'] == 3 and state['xp'] == xp + 10            # not 6 pieces / 24 xp of the new cabbage
    before = state['coins']
    apply(state, state, 'dig_up', dict(object='old1', revision=0), 30, str(uuid4()))   # no recorded price: min(current, r8)
    assert state['coins'] - before == undo.crop_cost(dict(id='beet'))
    # an r8 workshop job (linen from 3 flax) is collected with the stored outputs and XP
    state['objects'].append(dict(obj('loom', 'lm'), x=10, y=10))
    state['objects'][-1]['jobs'].append(dict(id='j1', recipe='linen', starts_at=0, ready_at=10, seconds=10, inputs={'flax': 3},
                                              outputs={'linen': 1}, xp=16, version='farm-2026-10-r8'))
    apply(state, state, 'collect', dict(object='lm', job='j1'), 10, str(uuid4()))
    assert state['inventory']['linen'] == 1
    validate_state(state)


def test_legacy_seed_costs_are_the_r8_prices():
    assert set(undo.LEGACY_SEED_COST) == set(CROPS)
    assert undo.LEGACY_SEED_COST['pepper'] == 50 and undo.LEGACY_SEED_COST['saffron'] == 96 and undo.LEGACY_SEED_COST['corn'] == 7
    assert undo.crop_cost(dict(id='mint')) == CROPS['mint']['cost']                   # the cheaper of the two
    assert undo.crop_cost(dict(id='chamomile')) == 62                                 # the r8 price is cheaper than the new one


def test_fatigue_threshold_covers_the_whole_fast_class():
    assert progression.SHORT_SECONDS['harvest'] == catalog.CROP_CLASS_SLOW == 1800
    assert all(c['seconds'] < progression.SHORT_SECONDS['harvest'] for c in CROPS.values() if crop_class(c['seconds']) == 'fast')
    assert all(c['seconds'] >= progression.SHORT_SECONDS['harvest'] for c in CROPS.values() if crop_class(c['seconds']) != 'fast')
