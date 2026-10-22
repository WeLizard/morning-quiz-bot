"""Textile chain (docs/tasks/FARM_TEXTILE_CHAIN.md, variant «a»): catalog law, reachability by level, old saves, lessons of Соня, orders."""
from copy import deepcopy

import pytest

from qw_farm import catalog
from qw_farm.catalog import (ANIMALS, BUILDINGS, ITEMS, LEVELS, LESSONS, NPC_SIGNATURE, NPC_TASTES, RECIPES, TEXTILE_BUILDING_IDS,
                             TEXTILE_ITEM_IDS, TEXTILE_RECIPE_IDS, VERSION, _xp_r9, level, validate)
from qw_farm.domain import FarmError, apply, make_order, project, reachable, validate_state
from qw_farm.expansion import settle, upgrade_state

from tests.test_farm_automation_r7 import T0, add_building, cmd, err, farm, obj

DAY = 86400


def at_level(lv, **kw):
    st = farm(xp=LEVELS[lv - 1], **kw)
    assert level(st['xp']) == lv
    return st


def value(items):
    return sum(ITEMS[k]['price'] * q for k, q in items.items())


def law_av(r):
    return r['seconds'] / 60 * (2.5 + 0.1 * r['level'])


def textile_farm(lv, animals=('sheep',)):
    st = at_level(lv)
    for i, kind in enumerate(('mill', 'feedmill', 'loom', 'spinnery', 'weavery', 'tailor')):
        add_building(st, kind, kind, 2 * i, 0)
    for i, animal in enumerate(animals):
        add_building(st, ANIMALS[animal]['building'], animal, 2 * i, 2, animal=animal)
    return st


# ---------------------------------------------------------------- catalog

def test_catalog_validates_and_version_is_not_bumped():
    validate()
    assert VERSION == 'farm-2026-10-r9'
    assert TEXTILE_ITEM_IDS == {r[0] for r in catalog.TEXTILE_ITEM_ROWS} and len(TEXTILE_ITEM_IDS) == 11
    assert len(TEXTILE_RECIPE_IDS) == 14 and TEXTILE_BUILDING_IDS == {'spinnery', 'weavery'}
    assert all(i in ITEMS for i in TEXTILE_ITEM_IDS)


def test_new_buildings_follow_the_document():
    assert (BUILDINGS['spinnery']['cost'], BUILDINGS['spinnery']['level']) == (300, 5)
    assert (BUILDINGS['weavery']['cost'], BUILDINGS['weavery']['level']) == (500, 6)
    assert not BUILDINGS['spinnery']['decor'] and not BUILDINGS['weavery']['decor']
    assert catalog.upgrade_kind('spinnery') == 'workshop' and catalog.upgrade_kind('weavery') == 'workshop'
    assert 'textile_mill' not in BUILDINGS   # the factory (section 12, step 7) is a separate project


@pytest.mark.parametrize('rid', sorted(TEXTILE_RECIPE_IDS))
def test_each_step_is_within_ten_percent_of_the_workshop_value_law(rid):
    r = RECIPES[rid]
    av = value(r['outputs']) - value(r['inputs'])
    assert abs(av / law_av(r) - 1) <= 0.10, (rid, av, law_av(r))
    assert r['seconds'] >= 120                                   # no fatigue (M3) on textile recipes
    assert r['xp'] == _xp_r9(r['building'], r['seconds'])        # XP by the building formulas, no new formula


def test_recipe_rows_match_the_document_numbers():
    expect = {   # id: (building, level, inputs, outputs, minutes, xp)
        'spin_yarn': ('spinnery', 5, {'wool': 4}, {'yarn': 2}, 12, 8),
        'down_yarn': ('spinnery', 5, {'rabbit_fluff': 4}, {'down_yarn': 2}, 16, 10),
        'linen_thread': ('spinnery', 6, {'flax': 2}, {'linen_thread': 2}, 10, 6),
        'alpaca_yarn': ('spinnery', 7, {'alpaca_fiber': 2}, {'alpaca_yarn': 2}, 10, 6),
        'weave_linen': ('weavery', 6, {'linen_thread': 2}, {'linen': 1}, 5, 4),
        'wool_cloth': ('weavery', 6, {'yarn': 2}, {'wool_cloth': 1}, 20, 13),
        'wool_plaid': ('weavery', 8, {'yarn': 3}, {'wool_plaid': 1}, 30, 20),
        'quilt': ('weavery', 12, {'wool_cloth': 1, 'linen': 1, 'feather': 2}, {'quilt': 1}, 30, 20),
        'silk_cloth': ('weavery', 34, {'silk': 2}, {'silk_cloth': 1}, 25, 16),
        'pillow': ('loom', 5, {'feather': 3}, {'pillow': 1}, 11, 7),
        'knit_scarf': ('loom', 7, {'alpaca_yarn': 1}, {'scarf': 1}, 14, 9),
        'down_shawl': ('loom', 8, {'down_yarn': 2}, {'down_shawl': 1}, 20, 13),
        'socks': ('loom', 9, {'yarn': 1}, {'socks': 2}, 10, 6),
        'robe': ('tailor', 17, {'wool_cloth': 2, 'down_yarn': 1}, {'robe': 1}, 30, 22),
        'silk_quilt': ('tailor', 36, {'silk_cloth': 1, 'swan_down': 2}, {'silk_quilt': 1}, 40, 30),
    }
    for rid, (b, lv, i, o, minutes, xp) in expect.items():
        r = RECIPES[rid]
        assert (r['building'], r['level'], r['inputs'], r['outputs'], r['seconds'], r['xp']) == (b, lv, i, o, minutes * 60, xp), rid
    assert {k: ITEMS[k]['price'] for k in TEXTILE_ITEM_IDS} == {
        'down_yarn': 80, 'linen_thread': 40, 'alpaca_yarn': 52, 'wool_cloth': 196, 'wool_plaid': 300, 'quilt': 445, 'silk_cloth': 618,
        'down_shawl': 226, 'socks': 50, 'robe': 598, 'silk_quilt': 1122}


def test_old_rows_and_prices_are_untouched_except_the_pillow():
    assert (RECIPES['yarn']['building'], RECIPES['yarn']['inputs'], RECIPES['yarn']['seconds']) == ('loom', {'wool': 2}, 900)
    assert (RECIPES['linen']['building'], RECIPES['linen']['inputs'], RECIPES['linen']['seconds']) == ('loom', {'flax': 2}, 1500)
    assert (RECIPES['scarf']['inputs'], RECIPES['scarf']['seconds']) == ({'alpaca_fiber': 2}, 1800)
    assert RECIPES['mittens']['inputs'] == {'rabbit_fluff': 2, 'yarn': 1}
    assert ITEMS['pillow']['price'] == 100 and ITEMS['yarn']['price'] == 67 and ITEMS['scarf']['price'] == 96


def test_chain_to_the_scarf_and_the_blanket_gives_the_documented_hourly_value():
    # alpaca fibre 2 -> alpaca yarn 2 -> scarf x2: 120 coins over 38 workshop minutes (189 per hour)
    raw = 2 * ITEMS['alpaca_fiber']['price']
    minutes = (RECIPES['alpaca_yarn']['seconds'] + 2 * RECIPES['knit_scarf']['seconds']) / 60
    av = 2 * ITEMS['scarf']['price'] - raw
    assert (av, minutes) == (120, 38) and round(av / minutes * 60) == 189
    # wool 4 + flax 2 + feathers 2 -> quilt: sum of steps close to 197 per hour
    steps = [('spin_yarn', 1), ('wool_cloth', 1), ('linen_thread', 1), ('weave_linen', 1), ('quilt', 1)]
    sec = sum(RECIPES[r]['seconds'] * n for r, n in steps) / 3600
    raw = 4 * ITEMS['wool']['price'] + 2 * ITEMS['flax']['price'] + 2 * ITEMS['feather']['price']
    assert (sec * 60, round((ITEMS['quilt']['price'] - raw) / sec)) == (77, 197)


# ---------------------------------------------------------------- reachability

def test_chain_opens_by_level():
    cases = [(5, 'yarn', True), (5, 'down_yarn', True), (5, 'linen_thread', False), (6, 'linen_thread', True), (6, 'wool_cloth', True),
             (6, 'wool_plaid', False), (6, 'alpaca_yarn', False), (7, 'alpaca_yarn', True), (8, 'wool_plaid', True), (8, 'down_shawl', True), (9, 'socks', True),
             (11, 'quilt', False), (12, 'quilt', True), (16, 'robe', False), (17, 'robe', True)]
    for lv, item, expected in cases:
        st = textile_farm(lv, ('sheep', 'rabbit', 'alpaca', 'goose'))
        st['inventory'] = {}
        assert (item in reachable(st)) is expected, (lv, item)


def test_without_the_new_buildings_the_old_chain_still_works():
    st = at_level(30)
    for kind in ('mill', 'feedmill', 'loom', 'tailor'):
        add_building(st, kind, kind, 0, 0)
    for animal in ('sheep', 'alpaca', 'angora', 'goose', 'rabbit'):
        add_building(st, ANIMALS[animal]['building'], animal, 0, 0, animal=animal)
    got = set(reachable(st))
    assert {'yarn', 'linen', 'scarf', 'alpaca_coat', 'pillow', 'mittens'} <= got
    assert not got & {'wool_cloth', 'wool_plaid', 'down_yarn', 'robe', 'linen_thread'}


# ---------------------------------------------------------------- old saves

def old_pillow_save():
    """A farm saved before the chain: a pillow batch on the loom with the OLD recipe (down 2 + feather 1, 25 min), 2nd batch queued."""
    st = at_level(12)
    loom = add_building(st, 'loom', 'lm', 0, 0, level=2)
    old = dict(recipe='pillow', seconds=1500, inputs={'rabbit_fluff': 2, 'feather': 1}, outputs={'pillow': 1}, xp=16, version=VERSION)
    loom['jobs'] = [dict(old, id='j1', starts_at=T0, ready_at=T0 + 1500), dict(old, id='j2', starts_at=T0 + 1500, ready_at=T0 + 3000)]
    loom['last_recipe'] = 'pillow'
    loom['recipes_memory'] = ['pillow', 'yarn', 'scarf']
    loom['recipe_cursor'] = 0
    st['inventory'] = {'feather': 5, 'wool': 4, 'alpaca_fiber': 4}
    for key in ('lessons',):
        st.pop(key, None)
    return st


def test_old_save_loads_with_queued_old_pillow_batches_memory_and_inventory():
    st = old_pillow_save()
    before_inv, before_mem = deepcopy(st['inventory']), deepcopy(obj(st, 'lm')['recipes_memory'])
    st = upgrade_state(st)
    upgrade_state(st)   # idempotent
    validate_state(st)
    assert st['lessons'] == {} and st['inventory'] == before_inv and obj(st, 'lm')['recipes_memory'] == before_mem
    assert st['schema_version'] == 2 and st['catalog'] == VERSION
    cmd(st, 'collect', {'object': 'lm', 'job': 'j1'}, T0 + 1500)          # finishes under its own stored xp/outputs
    assert st['inventory']['pillow'] == 1
    assert [j['id'] for j in obj(st, 'lm')['jobs']] == ['j2']


def old_yarn_save():
    """Loom saved before the chain: an old yarn batch (wool 2 -> yarn 1, 15 min) in the queue, yarn remembered, no lessons key."""
    st = at_level(8)
    loom = add_building(st, 'loom', 'lm', 0, 0)
    old = dict(id='y1', recipe='yarn', starts_at=T0, ready_at=T0 + 900, seconds=900, inputs={'wool': 2}, outputs={'yarn': 1}, xp=10, version=VERSION)
    loom['jobs'] = [old]
    loom['last_recipe'] = 'yarn'
    loom['recipes_memory'] = ['yarn', 'linen']
    loom['recipe_cursor'] = 0
    st['inventory'] = {'wool': 5, 'flax': 2}
    st.pop('lessons', None)
    return st


def test_old_yarn_job_collects_with_its_stored_xp_and_recipes_stay_forgettable_on_the_loom():
    st = upgrade_state(old_yarn_save())
    validate_state(st)
    xp = st['xp']
    cmd(st, 'collect', {'object': 'lm', 'job': 'y1'}, T0 + 900)
    assert st['inventory']['yarn'] == 1 and st['xp'] > xp
    assert obj(st, 'lm')['recipes_memory'] == ['yarn', 'linen']
    cmd(st, 'forget_recipe', {'object': 'lm', 'recipe': 'yarn'}, T0 + 901)     # the A7 scenario of the document, section 10
    assert obj(st, 'lm')['recipes_memory'] == ['linen']
    cmd(st, 'queue', {'object': 'lm', 'recipe': 'yarn'}, T0 + 902)             # the old loom path still works
    validate_state(st)


def test_cancelling_an_old_queued_batch_refunds_its_stored_inputs():
    st = upgrade_state(old_pillow_save())
    inv = dict(st['inventory'])
    cmd(st, 'cancel_job_and_forget_recipe', {'object': 'lm', 'job': 'j2'}, T0 + 10)
    assert st['inventory']['rabbit_fluff'] == inv.get('rabbit_fluff', 0) + 2 and st['inventory']['feather'] == inv['feather'] + 1


def test_remembered_pillow_restarts_with_the_new_inputs_and_other_memory_survives():
    st = upgrade_state(old_pillow_save())
    loom = obj(st, 'lm')
    loom['jobs'] = []
    st['inventory'] = {'feather': 3, 'wool': 2}
    from qw_farm.expansion import restartable
    r = restartable(st, loom, level(st['xp']))
    assert r['id'] == 'pillow' and r['inputs'] == {'feather': 3}
    st['inventory'] = {'wool': 2}
    assert restartable(st, loom, level(st['xp']))['id'] == 'yarn'     # next remembered recipe, old yarn still queued from memory
    assert obj(st, 'lm')['recipes_memory'] == ['pillow', 'yarn', 'scarf']


def test_old_recipes_still_queue_on_the_loom_and_new_ones_on_the_new_buildings():
    st = upgrade_state(textile_farm(12))
    st['inventory'] = {'wool': 10, 'flax': 4, 'alpaca_fiber': 2, 'feather': 3}
    cmd(st, 'queue', {'object': 'loom', 'recipe': 'yarn'})
    cmd(st, 'queue', {'object': 'loom', 'recipe': 'scarf'})
    cmd(st, 'queue', {'object': 'spinnery', 'recipe': 'spin_yarn'})
    assert err(st, 'queue', {'object': 'loom', 'recipe': 'spin_yarn'}) == 'wrong_building'
    job = obj(st, 'spinnery')['jobs'][0]
    assert job['outputs'] == {'yarn': 2} and job['seconds'] == 720 and job['xp'] == 8
    cmd(st, 'collect', {'object': 'spinnery', 'job': job['id']}, T0 + 720)
    assert st['inventory']['yarn'] == 2


# ---------------------------------------------------------------- lessons of Соня

def test_lesson_steps_are_sequential_gated_by_level_and_consume_goods():
    st = upgrade_state(textile_farm(5))
    st['inventory'] = {'yarn': 6}
    assert err(st, 'lesson_deliver', {'track': 'weaving'}) == 'locked'
    st['xp'] = LEVELS[5]
    assert err(st, 'lesson_deliver', {'track': 'nope'}) == 'unknown_item'
    assert err(st, 'lesson_deliver', {'track': 'weaving', 'x': 1}) == 'invalid_command'
    st['inventory'] = {'yarn': 5}
    assert err(st, 'lesson_deliver', {'track': 'weaving'}) == 'missing_goods'
    st['inventory'] = {'yarn': 7}
    cmd(st, 'lesson_deliver', {'track': 'weaving'})
    assert st['lessons'] == {'weaving': 1} and st['inventory']['yarn'] == 2     # 7 - 6 + 1 reward
    assert err(st, 'lesson_deliver', {'track': 'weaving'}) == 'locked'     # step 2 wants level 8
    st['xp'] = LEVELS[7]
    st['inventory'] = {'wool_cloth': 2}
    cmd(st, 'lesson_deliver', {'track': 'weaving'})
    assert st['lessons'] == {'weaving': 2} and st['inventory'] == {'wool_cloth': 0, 'down_yarn': 1}
    assert err(st, 'lesson_deliver', {'track': 'weaving'}) == 'lesson_done'
    validate_state(st)


def test_recipes_with_teach_are_listed_and_the_base_chain_needs_no_lesson():
    taught = {r['id'] for r in RECIPES.values() if r.get('teach')}
    assert taught == {'wool_plaid', 'down_shawl', 'quilt'}
    for rid in ('spin_yarn', 'weave_linen', 'wool_cloth', 'knit_scarf', 'yarn', 'linen', 'scarf'):
        assert 'teach' not in RECIPES[rid]
    assert all(r['teach']['npc'] == 'Кошка Соня' and r['teach']['track'] in LESSONS for r in RECIPES.values() if r.get('teach'))


def test_lesson_opens_plaid_shawl_and_quilt_earlier_in_queue_and_reachable():
    st = upgrade_state(textile_farm(6))
    add_building(st, 'rabbit_hutch', 'rb', 0, 0, animal='rabbit')
    st['inventory'] = {'yarn': 6}
    assert err(st, 'queue', {'object': 'weavery', 'recipe': 'wool_plaid'}) == 'wrong_building'
    assert 'wool_plaid' not in reachable(st)
    cmd(st, 'lesson_deliver', {'track': 'weaving'})                          # step 1 at level 6 (+1 yarn back)
    st['inventory'] = {'yarn': 3}
    assert 'wool_plaid' in reachable(st) and 'wool_cloth' in reachable(st)
    cmd(st, 'queue', {'object': 'weavery', 'recipe': 'wool_plaid'})          # level 8 recipe, taught 2 levels early
    # the shawl is taught one level early: not yet at 6, open at 7
    assert err(st, 'queue', {'object': 'loom', 'recipe': 'down_shawl'}) == 'wrong_building'
    st['xp'] = LEVELS[6]
    st['inventory'] = {'down_yarn': 2}
    cmd(st, 'queue', {'object': 'loom', 'recipe': 'down_shawl'})
    # the quilt needs step 2 (level 12 -> 10): closed after step 1 even at level 10
    st['xp'] = LEVELS[9]
    st['inventory'] = {'wool_cloth': 3, 'linen': 1, 'feather': 2}
    assert err(st, 'queue', {'object': 'weavery', 'recipe': 'quilt'}) == 'wrong_building'
    cmd(st, 'lesson_deliver', {'track': 'weaving'})
    cmd(st, 'queue', {'object': 'weavery', 'recipe': 'quilt'})
    st['xp'] = LEVELS[8]
    assert level(st['xp']) == 9
    st['inventory'] = {'wool_cloth': 1, 'linen': 1, 'feather': 2}
    assert err(st, 'queue', {'object': 'weavery', 'recipe': 'quilt'}) == 'wrong_building'


def test_helper_restart_uses_the_lesson_level_too():
    st = upgrade_state(textile_farm(6))
    weavery = obj(st, 'weavery')
    weavery.update(last_recipe='wool_plaid', recipes_memory=['wool_plaid'], recipe_cursor=0)
    st['inventory'] = {'yarn': 3}
    from qw_farm.expansion import restartable
    assert restartable(st, weavery, 6) is None
    st['lessons'] = {'weaving': 1}
    assert restartable(st, weavery, 6)['id'] == 'wool_plaid'


def test_lessons_ledger_validation_rejects_garbage():
    st = upgrade_state(at_level(6))
    st['lessons'] = {'weaving': 3}
    with pytest.raises(FarmError):
        validate_state(st)
    st['lessons'] = {'dancing': 1}
    with pytest.raises(FarmError):
        validate_state(st)


# ---------------------------------------------------------------- orders

def order_sample(st, name, n=3000):
    rows = []
    for seq in range(3, 3 + n):
        st['order_seq'] = seq
        o = make_order(st, 0, T0)
        if o['npc'] == name:
            rows.append(o)
    return rows


def late_farm():
    st = at_level(50)
    for b in BUILDINGS.values():
        if not b['decor']:
            add_building(st, b['id'], 'b_' + b['id'], 0, 0)
    for a in ANIMALS.values():
        add_building(st, a['building'], 'a_' + a['id'], 0, 0, animal=a['id'])
    return upgrade_state(st)


def test_sonya_asks_for_textile_about_half_of_the_time_and_pukh_keeps_his_share():
    st = late_farm()
    sig = set(NPC_SIGNATURE['Кошка Соня'])
    assert sig <= set(reachable(st))
    sonya = order_sample(st, 'Кошка Соня')
    share = sum(set(o['needs']) <= sig for o in sonya) / len(sonya)
    assert 0.45 <= share <= 0.65, share
    pukh = order_sample(st, 'Медведь Пух')
    pshare = sum(set(o['needs']) <= set(NPC_SIGNATURE['Медведь Пух']) for o in pukh) / len(pukh)
    assert 0.68 <= pshare <= 0.85, pshare


def test_signature_orders_never_exceed_the_price_cap_unless_single_piece():
    st = late_farm()
    sig = set(NPC_SIGNATURE['Кошка Соня'])
    seen_big = 0
    for o in order_sample(st, 'Кошка Соня', 6000):
        if set(o['needs']) <= sig and len(o['needs']) == 1:
            (item, qty), = o['needs'].items()
            seen_big += ITEMS[item]['price'] > 500
            assert qty == 1 or ITEMS[item]['price'] * qty <= catalog.SIGNATURE_MAX_VALUE, (item, qty)
    assert seen_big


def test_sonya_orders_follow_lessons_and_reachability():
    st = textile_farm(6)
    st = upgrade_state(st)
    st['inventory'] = {}
    names = set()
    for o in order_sample(st, 'Кошка Соня', 4000):
        names |= set(o['needs'])
    assert 'wool_plaid' not in names and 'quilt' not in names
    st['lessons'] = {'weaving': 1}
    names = set()
    for o in order_sample(st, 'Кошка Соня', 4000):
        names |= set(o['needs'])
    assert 'wool_plaid' in names and 'quilt' not in names


def test_special_request_caption_depends_on_the_kind_of_good():
    st = late_farm()
    st['market']['rep']['Кошка Соня'] = 10 ** 4
    st['market']['rep']['Филиныч'] = 10 ** 4
    titles = {}
    for seq in range(3, 3000):
        st['order_seq'] = seq
        o = make_order(st, 0, T0)
        if o.get('special'):
            titles.setdefault(o['npc'], set()).add(o['title'])
            if o['npc'] == 'Кошка Соня':
                assert o['title'] == 'Особая просьба: любимая вещь'
    assert titles['Филиныч'] == {'Особая просьба: любимое лакомство'}
    assert titles['Кошка Соня'] == {'Особая просьба: любимая вещь'}


def test_sonya_tastes_cover_the_new_garments():
    assert {'wool_plaid', 'down_shawl', 'quilt', 'silk_quilt', 'pillow', 'scarf'} <= set(NPC_TASTES['Кошка Соня'])
    assert all(i in ITEMS for i in NPC_TASTES['Кошка Соня'])


def test_semi_finished_goods_may_be_ordered_and_new_goods_reach_contracts():
    st = late_farm()
    assert {'wool_cloth', 'down_yarn', 'linen_thread', 'alpaca_yarn'} <= set(reachable(st))
    from qw_farm import market
    st['market']['contract_day'] = -1
    market.make_contracts(st, market.moscow_day(T0))
    assert st['market']['contracts']


def test_public_catalog_carries_lessons_for_the_client():
    pub = catalog.public_catalog()
    assert pub['lessons']['weaving']['steps'][0]['items'] == {'yarn': 6}
    assert pub['recipes']['quilt']['teach']['early'] == 2


def test_placeholder_art_exists_for_every_new_item_and_building():
    import re
    from pathlib import Path
    static = Path(__file__).resolve().parents[1] / 'qw_farm' / 'static'
    icons = set(re.findall(r'<symbol id="([a-z_0-9]+)"', (static / 'icons.svg').read_text(encoding='utf-8')))
    assert TEXTILE_ITEM_IDS <= icons
    types = re.search(r'const TYPES=\{([^}]*)\}', (static / 'scene_buildings.js').read_text(encoding='utf-8')).group(1)
    drawers = {m.split(':')[0].strip() for m in types.split(',')}
    assert TEXTILE_BUILDING_IDS <= drawers
