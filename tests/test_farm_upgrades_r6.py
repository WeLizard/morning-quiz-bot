"""Farm catalog r6: building upgrades 1 -> 3 (workshops, animal houses, barn), old-save compatibility."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from qw_farm.catalog import (ANIMALS, BARN_SELL_BONUS, ITEMS, LEVELS, MAX_BUILDING_LEVEL, RECIPES,
                             UPGRADES, VERSION, animal_batch, public_catalog, queue_slots, upgrade_cost, upgrade_kind,
                             validate)
from qw_farm.domain import FarmError, apply, new_farm, project, validate_state
from qw_farm.expansion import settle, upgrade_state

STATIC = Path(__file__).resolve().parents[1] / 'qw_farm' / 'static'


def farm(xp=LEVELS[29], coins=10 ** 7):
    state = upgrade_state(new_farm(str(uuid4()), 'Upgrades', 1000))
    state.update(xp=xp, coins=coins, starter_credit=0)
    state['inventory'].update(hay=50, flour=50, cheese=20, linen=20, wheat=100, feed=100, corn=50, clover=20)
    return state


def put(state, kind, oid='o1', animal=None, level=1, x=6, y=5):
    obj = dict(id=oid, type=kind, x=x, y=y, w=2, h=2, revision=0, level=level, jobs=[], animal=animal, animal_job=None)
    state['objects'].append(obj)
    return obj


def up(state, obj, now=2000):
    return apply(state, state, 'upgrade', dict(object=obj['id'], revision=obj['revision']), now, str(uuid4()))


def code(state, kind, data, now=2000):
    with pytest.raises(FarmError) as error:
        apply(state, state, kind, data, now, str(uuid4()))
    return error.value.code


def test_catalog_validates_and_version_bumped():
    validate()
    assert VERSION in {'farm-2026-10-r6', 'farm-2026-10-r7', 'farm-2026-10-r8', 'farm-2026-10-r9'}
    assert MAX_BUILDING_LEVEL == 3 and set(UPGRADES) == {2, 3}
    pub = public_catalog()['upgrades']
    assert pub['max'] == 3 and pub['kinds']['mill'] == 'workshop' and pub['kinds']['coop'] == 'animals'
    assert pub['kinds']['barn'] == 'barn'


def test_every_workshop_and_animal_house_is_upgradable_decor_and_house_are_not():
    for b in {r['building'] for r in RECIPES.values()}:
        assert upgrade_kind(b) == 'workshop'
    for b in {a['building'] for a in ANIMALS.values()}:
        assert upgrade_kind(b) in {'workshop', 'animals'}
    assert upgrade_kind('barn') == 'barn'
    for b in ('house', 'plot', 'flowerbed', 'bench', 'lantern', 'garage', 'basket', 'nope'):
        assert upgrade_cost(b, 2) is None
    assert upgrade_cost('mill', 1) is None and upgrade_cost('mill', 4) is None


def test_costs_scale_with_building_and_level():
    assert upgrade_cost('mill', 2) == dict(coins=200, items={'hay': 4, 'flour': 4}, level=4)
    assert upgrade_cost('mill', 3) == dict(coins=500, items={'cheese': 2, 'linen': 2}, level=8)
    assert upgrade_cost('confectionery', 2)['coins'] == 2400 and upgrade_cost('confectionery', 3)['coins'] == 4800
    assert upgrade_cost('barn', 2)['coins'] == 200 and upgrade_cost('barn', 3)['coins'] == 500
    for b in (*{r['building'] for r in RECIPES.values()}, 'barn'):
        c2, c3 = upgrade_cost(b, 2), upgrade_cost(b, 3)
        assert 0 < c2['coins'] < c3['coins'] and c2['level'] < c3['level']
        assert set(c2['items']) | set(c3['items']) <= set(ITEMS)


def test_upgrade_pays_coins_and_goods_and_raises_level():
    state = farm()
    mill = put(state, 'mill')
    coins, hay, flour = state['coins'], state['inventory']['hay'], state['inventory']['flour']
    up(state, mill)
    assert mill['level'] == 2 and mill['revision'] == 1
    assert state['coins'] == coins - 200
    assert state['inventory']['hay'] == hay - 4 and state['inventory']['flour'] == flour - 4
    cheese = state['inventory']['cheese']
    up(state, mill)
    assert mill['level'] == 3
    assert state['coins'] == coins - 700
    assert state['inventory']['cheese'] == cheese - 2 and state['inventory']['linen'] == 18
    validate_state(state)


def test_max_level_and_invalid_targets():
    state = farm()
    mill = put(state, 'mill', level=3)
    assert code(state, 'upgrade', dict(object='o1', revision=0)) == 'max_level'
    legacy = put(state, 'mill', 'o2', level=4)
    assert code(state, 'upgrade', dict(object='o2', revision=0)) == 'max_level'
    for kind in ('house', 'flowerbed'):
        put(state, kind, 'd_' + kind)
        assert code(state, 'upgrade', dict(object='d_' + kind, revision=0)) == 'cannot_upgrade'
    plot = next(o for o in state['objects'] if o['type'] == 'plot')
    assert code(state, 'upgrade', dict(object=plot['id'], revision=plot['revision'])) == 'cannot_upgrade'
    assert code(state, 'upgrade', dict(object='missing', revision=0)) == 'not_found'
    fresh = put(state, 'mill', 'o3')
    assert code(state, 'upgrade', dict(object='o3', revision=5)) == 'stale_object'
    assert code(state, 'upgrade', dict(object='o3')) == 'invalid_command'
    assert code(state, 'upgrade', dict(object='o3', revision=0, extra=1)) == 'invalid_command'
    assert mill['level'] == 3 and legacy['level'] == 4 and fresh['level'] == 1


def test_level_coins_and_goods_requirements_do_not_spend_anything():
    low = farm(LEVELS[2])
    mill = put(low, 'mill')
    before = deepcopy(low)
    assert code(low, 'upgrade', dict(object='o1', revision=0)) == 'locked'
    assert low == before
    poor = farm(coins=199)
    put(poor, 'mill')
    before = deepcopy(poor)
    assert code(poor, 'upgrade', dict(object='o1', revision=0)) == 'insufficient_coins'
    assert poor == before
    hungry = farm()
    put(hungry, 'mill')
    hungry['inventory']['hay'] = 3
    before = deepcopy(hungry)
    assert code(hungry, 'upgrade', dict(object='o1', revision=0)) == 'missing_goods'
    assert hungry == before  # no coins taken before the goods check failed
    mid = farm(LEVELS[3])
    m = put(mid, 'mill')
    up(mid, m)
    # level 3 of the building needs farm level 8
    assert code(mid, 'upgrade', dict(object='o1', revision=1)) == 'locked'
    assert mill['level'] == 1


def test_second_apply_with_old_revision_is_rejected_so_a_retry_never_double_charges():
    state = farm()
    mill = put(state, 'mill')
    rev = mill['revision']
    apply(state, state, 'upgrade', dict(object='o1', revision=rev), 2000, str(uuid4()))
    coins = state['coins']
    assert code(state, 'upgrade', dict(object='o1', revision=rev)) == 'stale_object'
    assert state['coins'] == coins and mill['level'] == 2


def test_workshop_levels_speed_up_recipes_and_widen_queue():
    seconds, slots = {}, {}
    for lv in (1, 2, 3):
        state = farm()
        mill = put(state, 'mill', level=lv)
        apply(state, state, 'queue', dict(object='o1', recipe='flour'), 2000, str(uuid4()))
        seconds[lv] = mill['jobs'][0]['seconds']
        n = 1
        while True:
            try:
                apply(state, state, 'queue', dict(object='o1', recipe='flour'), 2000, str(uuid4()))
                n += 1
            except FarmError as e:
                assert e.code == 'queue_full'
                break
        slots[lv] = n
    assert seconds == {1: 60, 2: 51, 3: 42}  # -15% per level
    assert slots == {1: 3, 2: 4, 3: 5} == {lv: queue_slots(lv) for lv in (1, 2, 3)}
    assert queue_slots(4) == 6  # legacy r5 level 4 keeps its slot count
    assert queue_slots(None) == 3  # no level = level 1


def test_speed_up_is_never_below_one_second_and_respects_game_speed():
    state = farm()
    mill = put(state, 'mill', level=3)
    apply(state, state, 'queue', dict(object='o1', recipe='flour'), 2000, str(uuid4()))
    assert mill['jobs'][0]['seconds'] == 42
    apply(state, state, 'queue', dict(object='o1', recipe='flour'), 2000, str(uuid4()), 60)
    assert mill['jobs'][1]['seconds'] == 1


def test_existing_queue_is_not_changed_by_upgrade():
    state = farm()
    mill = put(state, 'mill')
    apply(state, state, 'queue', dict(object='o1', recipe='flour'), 2000, str(uuid4()))
    job = deepcopy(mill['jobs'][0])
    up(state, mill)
    assert mill['jobs'][0] == job


@pytest.mark.parametrize('animal', sorted(ANIMALS))
def test_animal_capacity_scales_feed_product_and_cycle(animal):
    spec = ANIMALS[animal]
    for lv, mult, tm in ((1, 1, 1.0), (2, 2, 1.6), (3, 3, 2.2)):
        inputs, outputs, seconds = animal_batch(spec, lv)
        assert inputs == {k: q * mult for k, q in spec['inputs'].items()}
        assert outputs == {k: q * mult for k, q in spec['outputs'].items()}
        assert seconds == pytest.approx(spec['seconds'] * tm)
    # missing level = level 1, legacy level 4 = top effects
    assert animal_batch(spec, None) == animal_batch(spec, 1)
    assert animal_batch(spec, 4) == animal_batch(spec, 3)


def test_feed_and_collect_use_house_level():
    state = farm()
    coop = put(state, 'coop', 'c1', 'chicken', level=3)
    state['inventory']['feed'] = 10
    apply(state, state, 'feed', dict(object='c1'), 2000, str(uuid4()))
    assert state['inventory']['feed'] == 7
    assert coop['animal_job']['outputs'] == {'egg': 6}
    assert coop['animal_job']['ready_at'] == 2000 + 528  # ceil(240 * 2.2)
    eggs = state['inventory'].get('egg', 0)
    apply(state, state, 'collect_animal', dict(object='c1'), 2600, str(uuid4()))
    assert state['inventory']['egg'] == eggs + 6
    # not enough feed for a level 3 batch
    state['inventory']['feed'] = 2
    assert code(state, 'feed', dict(object='c1')) == 'missing_goods'


def test_helper_feeds_animals_with_level_batch():
    state = farm()
    coop = put(state, 'coop', 'c1', 'chicken', level=2)
    state['inventory']['feed'] = 5
    state['helpers']['shepherd'] = dict(acquired_at=0, total_runs=0, shift=dict(
        id='s', status='working', plan='short', starts_at=1000, until=5000, next_at=1000, interval=30, remaining=1,
        done=0, speed=1, role='animals', quota=1, version=VERSION))
    state['objects'] = [o for o in state['objects'] if o['type'] != 'coop' or o is coop]
    settle(state, 1100)
    assert state['inventory']['feed'] == 3  # 2 feed per level 2 batch
    assert coop['animal_job']['outputs'] == {'egg': 4}


def test_barn_upgrade_raises_sell_price_without_any_storage_limit():
    gains = {}
    for lv in (1, 2, 3):
        state = farm()
        next(o for o in state['objects'] if o['type'] == 'barn')['level'] = lv
        state['inventory']['clover'] = 100
        before = state['coins']
        apply(state, state, 'sell', dict(item='clover', qty=100), 2000, str(uuid4()))
        gains[lv] = state['coins'] - before
    price = ITEMS['clover']['price'] * 100
    assert gains == {1: price, 2: price * 105 // 100, 3: price * 110 // 100}
    assert BARN_SELL_BONUS == {1: 0, 2: 5, 3: 10}
    # a single cheap item never loses coins to rounding
    state = farm()
    next(o for o in state['objects'] if o['type'] == 'barn')['level'] = 3
    before = state['coins']
    apply(state, state, 'sell', dict(item='wheat', qty=1), 2000, str(uuid4()))
    assert state['coins'] - before == ITEMS['wheat']['price'] * 110 // 100 >= ITEMS['wheat']['price']
    # storage has no capacity: a huge stock is a valid state
    state['inventory']['wheat'] = 10 ** 6
    validate_state(state)


def test_barn_can_be_upgraded_and_a_farm_without_barn_sells_at_face_value():
    state = farm()
    barn = next(o for o in state['objects'] if o['type'] == 'barn')
    up(state, barn)
    up(state, barn)
    assert barn['level'] == 3
    assert code(state, 'upgrade', dict(object=barn['id'], revision=barn['revision'])) == 'max_level'
    state['objects'].remove(barn)
    before = state['coins']
    apply(state, state, 'sell', dict(item='wheat', qty=3), 2000, str(uuid4()))
    assert state['coins'] - before == ITEMS['wheat']['price'] * 3


def test_old_r5_save_loads_unchanged_and_levels_default_to_one():
    old = new_farm(str(uuid4()), 'Legacy', 1000)
    old['catalog'] = 'farm-2026-10-r5'
    old['xp'] = LEVELS[9]
    old['coins'] = 5000
    mill = put(old, 'mill', 'oldmill')
    del mill['level']  # objects older than the level field
    put(old, 'bakery', 'b4', level=4, x=0, y=6)  # legacy r5 maximum
    before = deepcopy(old)
    upgraded = upgrade_state(old)
    for key in ('id', 'coins', 'inventory', 'objects', 'orders', 'xp'):
        assert upgraded[key] == before[key]
    assert upgraded['catalog'] == VERSION
    validate_state(upgraded)
    apply(upgraded, upgraded, 'queue', dict(object='oldmill', recipe='flour'), 1500, str(uuid4()))
    old_mill = next(o for o in upgraded['objects'] if o['id'] == 'oldmill')
    assert old_mill['jobs'][0]['seconds'] == 60  # missing level = level 1
    upgraded['inventory'].update(hay=4, flour=8)
    apply(upgraded, upgraded, 'upgrade', dict(object='oldmill', revision=old_mill['revision']), 1500, str(uuid4()))
    assert old_mill['level'] == 2
    assert next(o for o in upgraded['objects'] if o['id'] == 'b4')['level'] == 4


def test_state_validation_rejects_broken_levels():
    state = farm()
    put(state, 'mill', level=9)  # out of the 1..4 range
    with pytest.raises(FarmError):
        validate_state(state)


def test_owner_projection_keeps_levels():
    a = farm()
    put(a, 'mill', level=2)
    view = project(a, a, 2000)
    assert view['is_owner'] and any(o.get('level') == 2 for o in view['objects'])


def test_frontend_wiring():
    app = (STATIC / 'app.js').read_text(encoding='utf-8')
    scene = (STATIC / 'scene.js').read_text(encoding='utf-8')
    buildings = (STATIC / 'scene_buildings.js').read_text(encoding='utf-8')
    assert "command('upgrade'" in app and 'S.catalog.upgrades' in app and 'Улучшить до' in app
    assert 'export function drawUpgrade' in buildings and 'drawUpgrade' in scene
    assert '.07*(o.level-1)' not in app  # the old hard-coded speed formula was replaced by the catalog table
