"""Fertilizers stages 1–2: bound byproducts and the ordinary compost workshop."""
import asyncio
from copy import deepcopy

import pytest

from qw_farm import friend_requests
from qw_farm.catalog import (ANIMALS, BUILDINGS, ITEMS, LEVELS, RECIPES, VERSION,
                             animal_batch, animal_xp, queue_slots, upgrade_cost)
from qw_farm.domain import FarmError, apply, new_farm, reachable, validate_state
from qw_farm.expansion import make_job, settle, upgrade_state


T0 = 1_800_000_000
EIGHT_HOURS = 8 * 3600
FERTILIZERS = ('manure', 'compost', 'humate')


def farm(fid='00000000-0000-0000-0000-00000000f101'):
    state = upgrade_state(new_farm(fid, 'Synthetic farm', T0), T0)
    state.update(size=20, xp=LEVELS[-1], coins=10**6, starter_credit=0,
                 objects=[], inventory={})
    state['progress'].update(day=10**9, dew=10**9)
    state['stats'].update(orders=3, harvests=4)
    return state


def cmd(state, kind, data, at=T0, other=None):
    return apply(state, other if other is not None else state, kind, data, at,
                 f'{kind}-{at}-{len(state["events"])}')


def rejected(state, kind, data, code, at=T0, other=None):
    before = deepcopy(state)
    peer_before = deepcopy(other)
    with pytest.raises(FarmError) as error:
        cmd(state, kind, data, at, other)
    assert error.value.code == code
    assert state == before
    assert other == peer_before


def building(state, kind, *, level=1, oid='building', animal=None):
    spec = BUILDINGS[kind]
    obj = dict(id=oid, type=kind, x=0, y=0, w=spec['w'], h=spec['h'],
               revision=0, level=level, jobs=[], animal=animal, animal_job=None)
    state['objects'].append(obj)
    return obj


def heap(state, level=1):
    return building(state, 'compost_heap', level=level)


@pytest.mark.parametrize('animal', sorted(ANIMALS))
@pytest.mark.parametrize('house_level', (1, 2, 3))
@pytest.mark.parametrize('collection', ('manual', 'group', 'shepherd'))
def test_one_manure_per_animal_batch_preserves_products_and_xp(animal, house_level, collection):
    state = farm()
    obj = building(state, ANIMALS[animal]['building'], level=house_level, animal=animal)
    inputs, outputs, _ = animal_batch(ANIMALS[animal], house_level)
    state['inventory'] = dict(inputs)
    cmd(state, 'feed', {'object': obj['id']})
    job = deepcopy(obj['animal_job'])
    assert job['outputs'] == outputs
    assert job['xp'] == animal_xp(ANIMALS[animal], house_level)
    at = job['ready_at']
    xp_before, crafts_before = state['xp'], state['stats']['crafts']
    stock_before = deepcopy(state['inventory'])
    if collection == 'manual':
        cmd(state, 'collect_animal', {'object': obj['id']}, at)
    elif collection == 'group':
        cmd(state, 'collect_group', {'group': 'animals', 'area': None}, at)
    else:
        obj['animal_repeat'] = False
        cmd(state, 'hire_helper', {'helper': 'shepherd'}, at)
        cmd(state, 'start_shift', {'worker': 'shepherd', 'shift': 'short'}, at)
        settle(state, at + 60)
    assert obj['animal_job'] is None
    assert state['xp'] - xp_before == job['xp']
    assert state['stats']['crafts'] - crafts_before == 1
    for item, qty in outputs.items():
        assert state['inventory'][item] == stock_before.get(item, 0) + qty
    expected_manure = 0 if animal in {'bees', 'silkworm'} else 1
    assert state['inventory'].get('manure', 0) == expected_manure
    settle(state, at + 120)
    assert state['inventory'].get('manure', 0) == expected_manure


def test_legacy_animal_job_keeps_legacy_xp_and_only_gets_manure_on_collection():
    state = farm()
    obj = building(state, 'cowshed', animal='cow')
    obj['animal_job'] = dict(ready_at=T0, outputs={'milk': 2}, version=VERSION)
    before = deepcopy(state)
    validate_state(state)
    upgrade_state(state, T0)
    assert state == before
    assert 'manure' not in state['inventory']
    xp_before = state['xp']
    cmd(state, 'collect_animal', {'object': obj['id']})
    assert state['inventory'] == {'milk': 2, 'manure': 1}
    assert state['xp'] - xp_before == 5
    rejected(state, 'collect_animal', {'object': obj['id']}, 'not_ready')


def test_old_save_upgrade_never_grants_retroactive_manure():
    state = farm()
    building(state, 'coop', animal='chicken')
    state['inventory'] = {'egg': 72, 'wool': 18}
    state['stats']['crafts'] = 100
    before = deepcopy(state)
    validate_state(state)
    upgrade_state(state, T0)
    upgrade_state(state, T0 + 86400)
    validate_state(state)
    assert state == before


def test_fertilizers_never_enter_reachable_even_with_stock_and_all_workshops():
    state = farm()
    state['inventory'] = dict.fromkeys(FERTILIZERS, 100)
    for kind in sorted({recipe['building'] for recipe in RECIPES.values()}):
        building(state, kind, oid=kind)
    for animal, spec in ANIMALS.items():
        building(state, spec['building'], oid=animal, animal=animal)
        assert 'manure' not in spec['outputs']
    assert not set(FERTILIZERS) & set(reachable(state))


@pytest.mark.parametrize('item', FERTILIZERS)
def test_bound_items_cannot_be_sold_listed_gifted_or_requested(item):
    state, peer = farm(), farm('00000000-0000-0000-0000-00000000f102')
    state['inventory'][item] = 10
    for left, right in ((state, peer), (peer, state)):
        left['neighbors'][right['id']] = dict(name=right['name'], status='accepted', accepted_at=T0 - 86401)
    assert ITEMS[item]['bound'] is True
    rejected(state, 'sell', {'item': item, 'qty': 1}, 'bound_item')
    rejected(state, 'list', {'item': item, 'qty': 1, 'unit_price': ITEMS[item]['price']}, 'bound_item')
    rejected(state, 'gift', {'item': item, 'qty': 1}, 'bound_item', other=peer)
    before = deepcopy(state)
    with pytest.raises(FarmError) as error:
        asyncio.run(friend_requests.create(None, state, 'synthetic-account',
                    dict(item=item, qty=1, offer_kind='free'), T0))
    assert error.value.code == 'bound_item'
    assert state == before


def test_heap_unlock_cost_footprint_and_singleton_are_enforced():
    state = farm()
    state['xp'] = LEVELS[4]
    rejected(state, 'build', dict(type='compost_heap', x=0, y=0), 'locked')
    state['xp'] = LEVELS[5]
    before = state['coins']
    cmd(state, 'build', dict(type='compost_heap', x=0, y=0))
    obj = state['objects'][0]
    assert (obj['type'], obj['w'], obj['h'], obj['level']) == ('compost_heap', 1, 1, 1)
    assert state['coins'] == before - 400
    rejected(state, 'build', dict(type='compost_heap', x=2, y=0), 'compost_heap_limit')
    validate_state(state)


@pytest.mark.parametrize('recipe,inputs', (
    ('compost_grass', {'manure': 2, 'grass': 4}),
    ('compost_manure', {'manure': 3}),
))
def test_compost_recipes_spend_exact_inputs_take_eight_hours_and_award_no_xp(recipe, inputs):
    state = farm()
    obj = heap(state)
    state['inventory'] = {**inputs, 'hay': 20}
    xp_before = state['xp']
    cmd(state, 'queue', {'object': obj['id'], 'recipe': recipe})
    job = obj['jobs'][0]
    assert job['inputs'] == inputs
    assert job['outputs'] == {'compost': 2}
    assert job['xp'] == 0
    assert job['ready_at'] - job['starts_at'] == EIGHT_HOURS
    assert state['inventory']['hay'] == 20
    assert all(state['inventory'][item] == 0 for item in inputs)
    rejected(state, 'collect', {'object': obj['id'], 'job': job['id']}, 'not_ready', T0 + EIGHT_HOURS - 1)
    cmd(state, 'collect', {'object': obj['id'], 'job': job['id']}, T0 + EIGHT_HOURS)
    assert state['inventory']['compost'] == 2
    assert state['xp'] == xp_before
    assert ITEMS['manure']['price'] == 1
    assert ITEMS['compost']['price'] == 3


@pytest.mark.parametrize('heap_level', (1, 2, 3))
def test_upgraded_heap_queue_is_sequential_and_cannot_exceed_six_compost_per_day(heap_level):
    state = farm()
    obj = heap(state, heap_level)
    state['inventory'] = {'manure': 100}
    for _ in range(queue_slots(heap_level)):
        cmd(state, 'queue', {'object': obj['id'], 'recipe': 'compost_manure'})
    assert [(job['starts_at'], job['ready_at']) for job in obj['jobs']] == [
        (T0 + i * EIGHT_HOURS, T0 + (i + 1) * EIGHT_HOURS) for i in range(queue_slots(heap_level))]
    rejected(state, 'queue', {'object': obj['id'], 'recipe': 'compost_manure'}, 'queue_full')
    before = state['xp']
    cmd(state, 'collect_group', {'group': 'workshops', 'area': None}, T0 + 86400)
    assert state['inventory']['compost'] == 6
    assert state['xp'] == before
    assert all(job['ready_at'] > T0 + 86400 for job in obj['jobs'])


def test_heap_upgrade_spends_the_common_cost_and_increases_slots():
    state = farm()
    obj = heap(state)
    for target in (2, 3):
        cost = upgrade_cost('compost_heap', target)
        state['inventory'] = dict(cost['items'])
        before = state['coins']
        cmd(state, 'upgrade', {'object': obj['id'], 'revision': obj['revision']})
        assert obj['level'] == target
        assert state['coins'] == before - cost['coins']
        assert all(state['inventory'][item] == 0 for item in cost['items'])
        assert queue_slots(obj['level']) == target + 2
        preview = make_job(obj, RECIPES['compost_manure'], T0, 1, 'preview')
        assert preview['seconds'] == EIGHT_HOURS


@pytest.mark.parametrize('mode', ('repeat_once', 'fill_queues'))
def test_common_bulk_commands_use_heap_recipe_memory_and_shared_stock(mode):
    state = farm()
    obj = heap(state)
    state['inventory'] = {'manure': 100, 'grass': 100}
    for recipe in ('compost_grass', 'compost_manure'):
        cmd(state, 'queue', {'object': obj['id'], 'recipe': recipe})
        cmd(state, 'set_recipe_repeat', {'object': obj['id'], 'recipe': recipe, 'enabled': True})
    cmd(state, 'collect_group', {'group': 'workshops', 'area': None}, T0 + 2 * EIGHT_HOURS)
    before = deepcopy(state['inventory'])
    cmd(state, mode, {'area': None}, T0 + 2 * EIGHT_HOURS)
    expected_count = 2 if mode == 'repeat_once' else queue_slots(1)
    assert len(obj['jobs']) == expected_count
    assert {job['recipe'] for job in obj['jobs']} == {'compost_grass', 'compost_manure'}
    for item in ('manure', 'grass'):
        used = sum(job['inputs'].get(item, 0) for job in obj['jobs'])
        assert state['inventory'][item] == before[item] - used
    assert all(job['seconds'] == EIGHT_HOURS for job in obj['jobs'])


@pytest.mark.parametrize('delay,refund', ((0, {'manure': 2, 'grass': 4}),
                                         (61, {'manure': 1, 'grass': 2})))
def test_cancel_heap_job_uses_common_refund_and_reschedules_queue(delay, refund):
    state = farm()
    obj = heap(state)
    state['inventory'] = {'manure': 4, 'grass': 8}
    for _ in range(2):
        cmd(state, 'queue', {'object': obj['id'], 'recipe': 'compost_grass'})
    xp_before = state['xp']
    cmd(state, 'cancel_job', {'object': obj['id'], 'job': obj['jobs'][0]['id']}, T0 + delay)
    assert state['inventory'] == refund
    assert len(obj['jobs']) == 1
    assert obj['jobs'][0]['starts_at'] == T0 + delay
    assert obj['jobs'][0]['ready_at'] == T0 + delay + EIGHT_HOURS
    assert state['xp'] == xp_before


def test_master_collects_heap_and_repeats_only_opted_in_recipe_during_shift():
    state = farm()
    obj = heap(state)
    state['inventory'] = {'manure': 100, 'hay': 50}
    cmd(state, 'queue', {'object': obj['id'], 'recipe': 'compost_manure'})
    cmd(state, 'set_recipe_repeat', {'object': obj['id'], 'recipe': 'compost_manure', 'enabled': True})
    xp_before = state['xp']
    at = T0 + EIGHT_HOURS
    cmd(state, 'hire_helper', {'helper': 'beaver_artisan'}, at)
    cmd(state, 'start_shift', {'worker': 'beaver_artisan', 'shift': 'night'}, at)
    settle(state, at + EIGHT_HOURS)
    assert state['inventory']['compost'] == 4
    assert state['inventory']['hay'] == 50
    assert state['xp'] == xp_before
    assert state['helpers']['beaver_artisan']['shift']['status'] == 'finished'
    assert state['stats']['crafts'] == 2
    assert all(job['seconds'] == EIGHT_HOURS for job in obj['jobs'])
    assert all(job['ready_at'] > at + EIGHT_HOURS for job in obj['jobs'])
    stock = deepcopy(state['inventory'])
    settle(state, T0 + 4 * 86400)
    assert state['inventory'] == stock


def test_master_collects_manual_heap_batch_without_repeating_when_not_enabled():
    state = farm()
    obj = heap(state)
    state['inventory'] = {'manure': 100}
    cmd(state, 'queue', {'object': obj['id'], 'recipe': 'compost_manure'})
    cmd(state, 'hire_helper', {'helper': 'beaver_artisan'})
    cmd(state, 'start_shift', {'worker': 'beaver_artisan', 'shift': 'night'})
    settle(state, T0 + EIGHT_HOURS)
    assert state['inventory']['compost'] == 2
    assert state['inventory']['manure'] == 97
    assert obj['jobs'] == []


# ---------------------------------------------------------------------------------------------------------------------
# Step 3: fertilizing beds and trees (docs/tasks/FARM_FERTILIZERS.md, sections 4.1-4.3 and 8)
# ---------------------------------------------------------------------------------------------------------------------
from qw_farm import orchard                      # noqa: E402
from qw_farm.catalog import CROPS, EXOTIC_CROPS  # noqa: E402
from qw_farm.domain import project               # noqa: E402
from qw_farm.undo import LATE_REFUND_PCT         # noqa: E402


def bed(state, oid, x=0, y=0, crop=None):
    obj = dict(id=oid, type='plot', x=x, y=y, w=1, h=1, revision=0, crop=crop)
    state['objects'].append(obj)
    return obj


def grown(crop_id, at=T0, fert=0, item=None):
    spec = CROPS[crop_id]
    crop = dict(id=crop_id, planted_at=at - spec['seconds'], ready_at=at, yield_qty=spec['yield_qty'], xp=spec['xp'],
                helped=False, watered=False, version=VERSION, cost=spec['cost'], gift=0)
    if fert:
        crop.update(fert=1, fert_item=item or 'compost')
    return crop


def stock(state, **items):
    for item, qty in items.items():
        state['inventory'][item] = qty


def switch(state, target, enabled=True, at=T0):
    cmd(state, 'fert_toggle', dict(target=target, enabled=enabled), at)


def plot_ref(obj):
    return dict(id=obj['id'], revision=obj['revision'])


# ---- the toggle command ------------------------------------------------------------------------------------------
def test_fert_toggle_has_a_strict_schema_defaults_to_off_and_is_owner_only():
    state, peer = farm(), farm('00000000-0000-0000-0000-00000000f102')
    assert 'fert_beds' not in state and 'fert_trees' not in state
    view = project(state, state, T0)
    assert (view['fert_beds'], view['fert_trees'], view['fert_carry']) == (False, False, {})
    switch(state, 'beds')
    assert state['fert_beds'] is True and state.get('fert_trees', False) is False
    switch(state, 'trees')
    switch(state, 'beds', False)
    assert (state['fert_beds'], state['fert_trees']) == (False, True)
    view = project(state, state, T0)
    assert (view['fert_beds'], view['fert_trees']) == (False, True)
    for data in (dict(target='field', enabled=True), dict(target='beds', enabled=1), dict(target='beds', enabled='yes'),
                 dict(target=['beds'], enabled=True), dict(target='beds'), dict(target='beds', enabled=True, extra=1)):
        rejected(state, 'fert_toggle', data, 'invalid_command')
    rejected(peer, 'fert_toggle', dict(target='beds', enabled=True), 'not_owner', other=state)
    assert 'fert_beds' not in peer


# ---- planting: every path, humate first ---------------------------------------------------------------------------
PLAYER_PLANT_PATHS = ('plant', 'exotic', 'plant_many')      # the player's own hands
MACHINE_PLANT_PATHS = ('tractor', 'combine')                 # automation: never spends a unit
PLANT_PATHS = PLAYER_PLANT_PATHS + MACHINE_PLANT_PATHS


def plant_path(state, path, plots):
    if path == 'plant':
        for p in plots:
            cmd(state, 'plant', dict(object=p['id'], crop='wheat', revision=p['revision']))
    elif path == 'exotic':
        spec = EXOTIC_CROPS['fire_pepper']
        state['inventory'][spec['seed']] = len(plots)
        for p in plots:
            cmd(state, 'plant', dict(object=p['id'], crop=spec['id'], revision=p['revision']))
    elif path == 'plant_many':
        cmd(state, 'plant_many', dict(crop='wheat', area=None))
    elif path == 'tractor':
        cmd(state, 'buy_equipment', dict(equipment='tractor'))
        cmd(state, 'machine_run', dict(machine='tractor', crop='wheat', plots=[plot_ref(p) for p in plots], replant=False))
    else:
        for p in plots:
            p['crop'] = grown('wheat')
        cmd(state, 'buy_equipment', dict(equipment='harvester'))
        cmd(state, 'machine_run', dict(machine='harvester', crop='', plots=[plot_ref(p) for p in plots], replant=True))


@pytest.mark.parametrize('path', PLAYER_PLANT_PATHS)
def test_every_player_planting_path_spends_humate_first_then_compost_and_marks_the_crop(path):
    state = farm()
    plots = [bed(state, f'b{i}', x=i) for i in range(3)]
    stock(state, humate=1, compost=1)
    switch(state, 'beds')
    plant_path(state, path, plots)
    marks = [(p['crop'].get('fert', 0), p['crop'].get('fert_item')) for p in plots]
    assert marks == [(1, 'humate'), (1, 'compost'), (0, None)]
    assert state['inventory']['humate'] == 0 and state['inventory']['compost'] == 0
    assert all(p['crop']['watered'] is False for p in plots)    # one planting shape for every path
    validate_state(state)


@pytest.mark.parametrize('path', MACHINE_PLANT_PATHS)
def test_tractor_and_combine_replant_never_spend_a_unit_even_with_the_switch_on(path):
    state = farm()
    plots = [bed(state, f'b{i}', x=i) for i in range(3)]
    stock(state, humate=2, compost=2)
    switch(state, 'beds')
    plant_path(state, path, plots)
    assert all(p['crop'] and 'fert' not in p['crop'] and 'fert_item' not in p['crop'] for p in plots)
    assert (state['inventory']['humate'], state['inventory']['compost']) == (2, 2)
    validate_state(state)


@pytest.mark.parametrize('path', PLANT_PATHS)
def test_planting_spends_nothing_when_the_switch_is_off_or_the_stock_is_empty(path):
    state = farm()
    plots = [bed(state, f'b{i}', x=i) for i in range(2)]
    stock(state, humate=2, compost=2)
    plant_path(state, path, plots)
    assert all('fert' not in p['crop'] for p in plots)
    assert (state['inventory']['humate'], state['inventory']['compost']) == (2, 2)
    empty = farm()
    plots = [bed(empty, f'b{i}', x=i) for i in range(2)]
    switch(empty, 'beds')
    plant_path(empty, path, plots)
    assert all('fert' not in p['crop'] for p in plots)


def test_planting_ignores_the_tree_switch_and_never_spends_manure():
    state = farm()
    p = bed(state, 'b0')
    stock(state, manure=5, compost=1)
    switch(state, 'trees')
    cmd(state, 'plant', dict(object='b0', crop='wheat', revision=0))
    assert 'fert' not in p['crop'] and state['inventory']['manure'] == 5 and state['inventory']['compost'] == 1
    p['crop'] = None
    switch(state, 'beds')
    stock(state, compost=0)
    cmd(state, 'plant', dict(object='b0', crop='wheat', revision=p['revision']))
    assert 'fert' not in p['crop'] and state['inventory']['manure'] == 5


def test_unfertilized_planting_keeps_the_shape_of_a_bed_crop():
    state = farm()
    p = bed(state, 'b0')
    cmd(state, 'plant', dict(object='b0', crop='wheat', revision=0))
    spec = CROPS['wheat']
    assert p['crop'] == dict(id='wheat', planted_at=T0, ready_at=T0 + spec['seconds'], yield_qty=spec['yield_qty'], xp=spec['xp'],
                             helped=False, watered=False, version=VERSION, cost=spec['cost'], gift=0)


# ---- harvesting: every path, the effect only here -----------------------------------------------------------------
HARVEST_PATHS = ('harvest', 'collect_all', 'collect_group', 'combine', 'helper')


def harvest_path(state, path, plots, at=T0):
    if path == 'harvest':
        for p in plots:
            cmd(state, 'harvest', dict(object=p['id'], revision=p['revision']), at)
    elif path == 'collect_all':
        cmd(state, 'collect_all', {}, at)
    elif path == 'collect_group':
        cmd(state, 'collect_group', dict(group='plots', area=None), at)
    elif path == 'combine':
        cmd(state, 'buy_equipment', dict(equipment='harvester'), at)
        cmd(state, 'machine_run', dict(machine='harvester', crop='', plots=[plot_ref(p) for p in plots], replant=False), at)
    else:
        cmd(state, 'hire_helper', dict(helper='fox_picker'), at)
        cmd(state, 'start_shift', dict(worker='fox_picker', shift='day'), at)
        settle(state, at + 7200)


@pytest.mark.parametrize('path', HARVEST_PATHS)
def test_every_harvest_path_pays_the_bonus_with_a_carry_and_leaves_experience_alone(path):
    plain, fed = farm(), farm()
    for state, fert in ((plain, 0), (fed, 1)):
        for i in range(4):
            bed(state, f'b{i}', x=i, crop=grown('wheat', fert=fert))
    harvest_path(plain, path, plain['objects'])
    harvest_path(fed, path, fed['objects'])
    assert plain['inventory']['wheat'] == 12
    assert fed['inventory']['wheat'] == 12 + 3          # 4 beds * 3 * 250 permille = 3000 permille = 3 whole units
    assert fed['fert_carry'] == {}
    assert fed['xp'] == plain['xp'] and fed['stats']['harvests'] == plain['stats']['harvests'] == 4 + 4
    assert all(o['crop'] is None and o['last_crop'] == 'wheat' for o in fed['objects'])
    validate_state(fed)


def test_fraction_accumulates_so_a_two_unit_yield_gives_two_extra_in_four_harvests():
    state = farm()
    p = bed(state, 'b0')
    history = []
    for i in range(4):
        p['crop'] = grown('strawberry', at=T0 + i, fert=1)
        assert p['crop']['yield_qty'] == 2
        before = state['inventory'].get('strawberry', 0)
        cmd(state, 'harvest', dict(object='b0', revision=p['revision']), T0 + i)
        history += [state['inventory']['strawberry'] - before, state.get('fert_carry', {}).get('strawberry', 0)]
    assert history == [2, 500, 3, 0, 2, 500, 3, 0]
    assert state['inventory']['strawberry'] == 2 * 4 + 2


def test_carry_is_kept_per_crop_and_bounded():
    state = farm()
    a, b = bed(state, 'a'), bed(state, 'b', x=1)
    a['crop'], b['crop'] = grown('wheat', fert=1), grown('carrot', fert=1)
    cmd(state, 'collect_all', {})
    assert state['fert_carry'] == {'wheat': 750, 'carrot': 750}
    validate_state(state)


def test_unfertilized_harvest_creates_no_carry():
    state = farm()
    bed(state, 'a', crop=grown('wheat'))
    cmd(state, 'harvest', dict(object='a', revision=0))
    assert state['inventory']['wheat'] == 3 and 'fert_carry' not in state


def test_switching_off_does_not_cancel_an_already_fertilized_bed():
    state = farm()
    p = bed(state, 'a', crop=grown('strawberry', fert=1))
    switch(state, 'beds', False)
    cmd(state, 'harvest', dict(object='a', revision=p['revision']))
    assert state['inventory']['strawberry'] == 2 and state['fert_carry'] == {'strawberry': 500}


def test_neighbour_help_stacks_with_fertilizer_and_a_guest_cannot_fertilize():
    state, guest = farm(), farm('00000000-0000-0000-0000-00000000f102')
    stock(state, compost=1)
    switch(state, 'beds')
    p = bed(state, 'a')
    cmd(state, 'plant', dict(object='a', crop='carrot', revision=0))
    assert p['crop']['fert'] == 1
    ready = p['crop']['ready_at']
    for left, right in ((state, guest), (guest, state)):
        left['neighbors'][right['id']] = dict(name=right['name'], status='accepted', accepted_at=T0 - 86401)
    cmd(guest, 'help', dict(object='a', revision=p['revision']), T0 + 1, other=state)
    assert p['crop']['ready_at'] < ready and p['crop']['fert'] == 1 and p['crop']['helped'] is True
    stock(guest, compost=5, humate=5)
    guest_before, state_before = deepcopy(guest), deepcopy(state)
    for kind, data in (('fert_toggle', dict(target='beds', enabled=True)),
                       ('tree_care', dict(object='a', action='fertilize', item=None))):
        with pytest.raises(FarmError) as error:
            cmd(guest, kind, data, other=state)
        assert error.value.code == 'not_owner'
    assert guest == guest_before and state == state_before


# ---- dig up ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize('delay', (0, 59, 61, 100))
@pytest.mark.parametrize('item', ('compost', 'humate'))
def test_dig_up_unripe_fertilized_bed_returns_exactly_the_unit_at_any_moment(delay, item):
    state = farm()
    p = bed(state, 'a')
    stock(state, **{item: 1})
    switch(state, 'beds')
    cmd(state, 'plant', dict(object='a', crop='carrot', revision=0))
    assert state['inventory'][item] == 0
    coins = state['coins']
    cmd(state, 'dig_up', dict(object='a', revision=p['revision']), T0 + delay)
    cost = CROPS['carrot']['cost']
    assert p['crop'] is None and state['inventory'][item] == 1 and 'fert_carry' not in state
    assert state['coins'] - coins == (cost if delay <= 60 else cost * LATE_REFUND_PCT // 100)


def test_plant_and_dig_up_loops_never_move_the_carry_or_the_stock():
    state = farm()
    p = bed(state, 'a')
    stock(state, compost=1)
    for i in range(6):
        switch(state, 'beds', i % 2 == 0)
        cmd(state, 'plant', dict(object='a', crop='carrot', revision=p['revision']), T0 + 100 * i)
        cmd(state, 'dig_up', dict(object='a', revision=p['revision']), T0 + 100 * i + 1)
        assert state['inventory']['compost'] == 1
    assert 'fert_carry' not in state


def test_dig_up_of_an_overseas_bed_returns_the_unit_and_the_seed_by_the_old_rules():
    state = farm()
    spec = EXOTIC_CROPS['fire_pepper']
    p = bed(state, 'a')
    stock(state, compost=1)
    state['inventory'][spec['seed']] = 2
    switch(state, 'beds')
    cmd(state, 'plant', dict(object='a', crop=spec['id'], revision=0))
    cmd(state, 'dig_up', dict(object='a', revision=p['revision']), T0 + 61)
    assert state['inventory']['compost'] == 1 and state['inventory'][spec['seed']] == 1      # late: seed lost, unit back
    cmd(state, 'plant', dict(object='a', crop=spec['id'], revision=p['revision']), T0 + 100)
    cmd(state, 'dig_up', dict(object='a', revision=p['revision']), T0 + 110)
    assert state['inventory']['compost'] == 1 and state['inventory'][spec['seed']] == 1      # in the window: seed back too


def test_ripe_fertilized_bed_cannot_be_dug_up():
    state = farm()
    p = bed(state, 'a', crop=grown('wheat', fert=1))
    rejected(state, 'dig_up', dict(object='a', revision=0), 'ripe')
    assert p['crop']['fert'] == 1


# ---- trees -----------------------------------------------------------------------------------------------------------
def adult_tree(state, species='apple', x=10, y=10):
    """Plant a sapling and take its first harvest: returns the tree (now adult) and the time its current cycle started."""
    cmd(state, 'plant_tree', dict(species=species, x=x, y=y, voucher=None), T0)
    obj = next(o for o in state['objects'] if o['type'] == 'tree')
    t = T0
    while obj['harvests'] < 1:
        t = obj['fruit']['ready_at']
        cmd(state, 'harvest', dict(object=obj['id'], revision=obj['revision']), t)
    return obj, t


def fertilize(state, obj, at):
    cmd(state, 'tree_care', dict(object=obj['id'], action='fertilize', item=None), at)


def test_adult_tree_cycle_takes_humate_first_and_marks_the_fruit_when_the_switch_is_on():
    state = farm()
    stock(state, humate=1, compost=1)
    switch(state, 'trees')
    obj, _ = adult_tree(state)
    assert obj['harvests'] == 1
    assert obj['fruit'].get('fert') == 1 and obj['fruit']['fert_item'] == 'humate'
    assert state['inventory']['humate'] == 0 and state['inventory']['compost'] == 1
    validate_state(state)


def test_sapling_is_not_fertilized_at_planting_and_a_closed_switch_spends_nothing():
    state = farm()
    stock(state, compost=3)
    switch(state, 'trees')
    cmd(state, 'plant_tree', dict(species='apple', x=3, y=3, voucher=None), T0)
    sapling = next(o for o in state['objects'] if o['type'] == 'tree')
    assert 'fert' not in sapling['fruit'] and state['inventory']['compost'] == 3
    other = farm()
    stock(other, compost=3)
    obj, _ = adult_tree(other)
    assert 'fert' not in obj['fruit'] and other['inventory']['compost'] == 3


def test_adult_tree_without_stock_starts_an_ordinary_cycle():
    state = farm()
    switch(state, 'trees')
    obj, _ = adult_tree(state)
    assert 'fert' not in obj['fruit']
    validate_state(state)


def test_manual_fertilize_marks_a_growing_cycle_once_and_checks_stock_and_ripeness():
    state = farm()
    obj, t = adult_tree(state)
    care = dict(object=obj['id'], action='fertilize', item=None)
    rejected(state, 'tree_care', care, 'missing_goods', t)
    stock(state, compost=1, humate=1)
    rejected(state, 'tree_care', dict(object=obj['id'], action='fertilize', item='compost'), 'invalid_command', t)
    rejected(state, 'tree_care', care, 'not_growing', obj['fruit']['ready_at'])
    fertilize(state, obj, t)
    assert (obj['fruit']['fert'], obj['fruit']['fert_item']) == (1, 'humate')
    assert state['inventory']['humate'] == 0 and state['inventory']['compost'] == 1
    rejected(state, 'tree_care', care, 'already_fertilized', t)
    assert orchard.tree_view(state, obj, t)['fert'] == 1
    assert project(state, state, t)['orchard_view']['trees'][obj['id']]['fert'] == 1


def test_manual_fertilize_also_works_on_a_sapling():
    state = farm()
    stock(state, compost=1)
    cmd(state, 'plant_tree', dict(species='apple', x=3, y=3, voucher=None), T0)
    sapling = next(o for o in state['objects'] if o['type'] == 'tree')
    fertilize(state, sapling, T0 + 5)
    assert sapling['fruit']['fert'] == 1 and state['inventory']['compost'] == 0


def test_tree_effect_is_a_quarter_with_the_same_xp_and_an_untouched_golden_chance():
    plain, fed = farm(), farm()
    po, t = adult_tree(plain)
    fo, _ = adult_tree(fed)
    stock(fed, compost=1)
    fertilize(fed, fo, t)
    frozen = {k: v for k, v in fo['fruit'].items() if k not in {'fert', 'fert_item'}}
    assert frozen == po['fruit']       # qty, xp, pest, golden and gold_hidden are exactly those of the unfertilized cycle
    qty, at = po['fruit']['qty'], po['fruit']['ready_at']
    got = {}
    for name, state, o in (('plain', plain, po), ('fed', fed, fo)):
        before = state['inventory'].get('apple', 0), state['xp'], state['stats']['harvests']
        cmd(state, 'harvest', dict(object=o['id'], revision=o['revision']), at)
        got[name] = (state['inventory']['apple'] - before[0], state['xp'] - before[1], state['stats']['harvests'] - before[2])
    extra, rest = divmod(qty * 250, 1000)
    assert got['plain'][0] == qty and got['fed'][0] == qty + extra
    assert got['fed'][1:] == got['plain'][1:]
    assert fed['fert_carry'] == ({'apple': rest} if rest else {})
    assert 'fert' not in fo['fruit']      # no switch and no stock: the next cycle is not fertilized


def test_tree_fraction_carries_over_cycles_and_pruning_stacks():
    state = farm()
    obj, t = adult_tree(state)
    carry, total_extra = 0, 0
    for _ in range(4):
        stock(state, compost=1)
        fertilize(state, obj, t)
        qty, t = obj['fruit']['qty'], obj['fruit']['ready_at']
        before = state['inventory'].get('apple', 0)
        cmd(state, 'harvest', dict(object=obj['id'], revision=obj['revision']), t)
        extra, carry = divmod(carry + qty * 250, 1000)
        assert state['inventory']['apple'] - before == qty + extra
        assert state.get('fert_carry', {}).get('apple', 0) == carry
        total_extra += extra
    assert total_extra > 0
    pruned = farm()
    obj2, t2 = adult_tree(pruned)
    obj2['prune_at'] = obj2['harvests']          # dry branches are waiting for the pruner
    stock(pruned, compost=1)
    fertilize(pruned, obj2, t2)
    base = obj2['fruit']['qty']
    cmd(pruned, 'tree_care', dict(object=obj2['id'], action='prune', item=None), t2)
    assert obj2['fruit']['qty'] == base + 1 and obj2['fruit']['fert'] == 1
    before = pruned['inventory'].get('apple', 0)
    cmd(pruned, 'harvest', dict(object=obj2['id'], revision=obj2['revision']), obj2['fruit']['ready_at'])
    assert pruned['inventory']['apple'] - before == base + 1 + (base + 1) * 250 // 1000


def test_uproot_in_the_undo_window_returns_the_unit_and_later_does_not():
    state = farm()
    stock(state, humate=1)
    cmd(state, 'plant_tree', dict(species='apple', x=3, y=3, voucher=None), T0)
    sapling = next(o for o in state['objects'] if o['type'] == 'tree')
    fertilize(state, sapling, T0 + 1)
    assert state['inventory']['humate'] == 0
    cmd(state, 'demolish', dict(object=sapling['id'], revision=sapling['revision']), T0 + 30)
    assert state['inventory']['humate'] == 1 and not [o for o in state['objects'] if o['type'] == 'tree']
    late = farm()
    stock(late, compost=1)
    cmd(late, 'plant_tree', dict(species='apple', x=3, y=3, voucher=None), T0)
    tree_obj = next(o for o in late['objects'] if o['type'] == 'tree')
    fertilize(late, tree_obj, T0 + 1)
    cmd(late, 'demolish', dict(object=tree_obj['id'], revision=tree_obj['revision']), T0 + 120)
    assert late['inventory']['compost'] == 0 and late['inventory']['wood'] > 0


def test_uproot_of_a_ripe_tree_does_not_lose_the_unit_of_the_cycle_the_harvest_just_started():
    state = farm()
    obj, _ = adult_tree(state)
    switch(state, 'trees')
    stock(state, compost=1)
    cmd(state, 'demolish', dict(object=obj['id'], revision=obj['revision']), obj['fruit']['ready_at'])
    assert state['inventory']['compost'] == 1


def test_guest_projection_shows_the_look_of_fertilized_trees_and_beds_but_never_the_carry_or_the_item():
    state, guest = farm(), farm('00000000-0000-0000-0000-00000000f102')
    obj, t = adult_tree(state)
    stock(state, humate=1)
    fertilize(state, obj, t)
    fed = bed(state, 'a', crop=grown('strawberry', fert=1, item='humate'))
    bed(state, 'plain', x=1, crop=grown('wheat'))
    state.update(fert_carry={'strawberry': 500}, fert_beds=True)
    state['settings']['visibility'] = 'public'
    view = project(state, guest, t)
    tree_view = next(o for o in view['objects'] if o['type'] == 'tree')
    assert tree_view['fruit'] == {'ready_at': obj['fruit']['ready_at'], 'helped': False, 'fert': 1}
    crops = {o['id']: o['crop'] for o in view['objects'] if o['type'] == 'plot'}
    assert crops['a']['fert'] == 1 and 'fert_item' not in crops['a'] and 'fert' not in crops['plain']
    for key in ('fert_carry', 'fert_beds', 'fert_trees'):
        assert key not in view
    owner = project(state, state, t)
    assert owner['fert_carry'] == {'strawberry': 500} and owner['fert_beds'] is True and owner['fert_trees'] is False
    assert next(o for o in owner['objects'] if o['id'] == 'a')['crop']['fert_item'] == 'humate'
    assert fed['crop']['fert_item'] == 'humate'      # a guest view does not mutate the source


# ---- validation and old saves -------------------------------------------------------------------------------------
def test_old_save_without_any_fertilizer_field_is_valid_and_upgrade_does_not_add_fields():
    state = farm()
    bed(state, 'a', crop=grown('wheat'))
    before = deepcopy(state)
    validate_state(state)
    upgrade_state(state, T0)
    assert state == before
    assert not {'fert_beds', 'fert_trees', 'fert_carry'} & set(state)
    cmd(state, 'harvest', dict(object='a', revision=0))
    assert state['inventory']['wheat'] == 3


@pytest.mark.parametrize('mutate', (
    lambda s: s.update(fert_beds=1),
    lambda s: s.update(fert_trees='yes'),
    lambda s: s.update(fert_carry=[]),
    lambda s: s.update(fert_carry={'wheat': 1000}),
    lambda s: s.update(fert_carry={'wheat': -1}),
    lambda s: s.update(fert_carry={'wheat': True}),
    lambda s: s.update(fert_carry={'unknown_item': 5}),
    lambda s: s['objects'][0]['crop'].update(fert=2),
    lambda s: s['objects'][0]['crop'].update(fert=True),
    lambda s: s['objects'][0]['crop'].update(fert=1, fert_item='manure'),
    lambda s: s['objects'][0]['crop'].update(fert_item='compost'),
    lambda s: s['objects'][1]['fruit'].update(fert=3),
))
def test_validate_state_rejects_broken_fertilizer_fields(mutate):
    state = farm()
    bed(state, 'a', crop=grown('wheat'))
    cmd(state, 'plant_tree', dict(species='apple', x=5, y=5, voucher=None))
    validate_state(state)
    mutate(state)
    with pytest.raises(FarmError) as error:
        validate_state(state)
    assert error.value.code == 'invalid_fertilizer'


def test_valid_fertilizer_fields_pass_validation():
    state = farm()
    bed(state, 'a', crop=grown('wheat', fert=1, item='humate'))
    bed(state, 'b', x=1, crop=grown('wheat', fert=0))
    state.update(fert_beds=True, fert_trees=False, fert_carry={'wheat': 999, 'carrot': 0})
    validate_state(state)


def test_helper_harvest_of_a_tree_pays_the_paid_bonus_but_does_not_fertilize_the_next_cycle():
    state = farm()
    obj, t = adult_tree(state)
    stock(state, compost=2)
    switch(state, 'trees')
    fertilize(state, obj, t)
    qty, ready = obj['fruit']['qty'], obj['fruit']['ready_at']
    before = state['inventory'].get('apple', 0)
    cmd(state, 'hire_helper', dict(helper='fox_picker'), ready)
    cmd(state, 'start_shift', dict(worker='fox_picker', shift='day'), ready)
    settle(state, ready + 7200)
    assert obj['harvests'] == 2 and obj['fruit']['started_at'] == ready
    assert state['inventory']['apple'] - before == qty + qty * 250 // 1000      # the paid effect does not depend on who harvests
    assert 'fert' not in obj['fruit'] and state['inventory']['compost'] == 1     # the helper's harvest spends no unit on the new cycle
    # the same tree harvested by the player starts a fertilized cycle
    mine = farm()
    own, t2 = adult_tree(mine)
    stock(mine, compost=2)
    switch(mine, 'trees')
    fertilize(mine, own, t2)
    cmd(mine, 'harvest', dict(object=own['id'], revision=own['revision']), own['fruit']['ready_at'])
    assert own['fruit']['fert'] == 1 and mine['inventory']['compost'] == 0


def test_player_bulk_tree_harvest_starts_a_fertilized_cycle():
    state = farm()
    obj, t = adult_tree(state)
    stock(state, humate=1)
    switch(state, 'trees')
    cmd(state, 'collect_group', dict(group='plots', area=None), obj['fruit']['ready_at'])
    assert obj['harvests'] == 2 and obj['fruit']['fert'] == 1 and state['inventory']['humate'] == 0
