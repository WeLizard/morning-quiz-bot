"""Farm catalog r7: helpers with zones, artisans, bulk actions, mass planting, bigger land limits."""
from copy import deepcopy
from pathlib import Path
import time
from uuid import uuid4

import pytest

from qw_farm.catalog import (CROPS, EQUIPMENT, HELPERS, ITEMS, LEVELS, OBJECT_LIMITS, PLOT_LIMITS, RECIPES, SHIFTS,
                             VERSION, public_catalog, validate)
from qw_farm.domain import FarmError, apply, new_farm, project, validate_state
from qw_farm.expansion import settle, upgrade_state

STATIC = Path(__file__).resolve().parents[1] / 'qw_farm' / 'static'
T0 = 1000
NEW_HELPERS = ('fox_picker', 'hamster_reaper', 'cat_keeper', 'beaver_artisan', 'badger_artisan')


def farm(coins=10 ** 6, size=20, xp=LEVELS[29], fid='00000000-0000-0000-0000-00000000f001'):
    state = upgrade_state(new_farm(fid, 'Auto', T0))
    state.update(size=size, xp=xp, coins=coins, starter_credit=0, objects=[], inventory={})
    state['progress'].update(day=10 ** 9, dew=10 ** 9)  # r9: no Morning dew (M1) here: exact XP expectations
    return state


def cmd(state, kind, data, at=T0):
    return apply(state, state, kind, data, at, f'{kind}-{at}-{len(state["events"])}')


def err(state, kind, data, at=T0):
    before = deepcopy(state)
    with pytest.raises(FarmError) as error:
        cmd(state, kind, data, at)
    assert state == before or kind in {'plant_many'}  # failures leave the farm untouched
    return error.value.code


def add_plots(state, n, crop='wheat', ready_at=T0, x0=0, y0=0, width=20, prefix='p'):
    spec = CROPS[crop]
    for i in range(n):
        x, y = x0 + i % width, y0 + i // width
        state['objects'].append(dict(
            id=f'{prefix}{y:02d}{x:02d}', type='plot', x=x, y=y, w=1, h=1, revision=0,
            crop=dict(id=crop, planted_at=ready_at - spec['seconds'], ready_at=ready_at, yield_qty=spec['yield_qty'],
                      xp=spec['xp'], helped=False, watered=False, version=VERSION) if ready_at is not None else None))


def add_building(state, kind, oid, x, y, animal=None, last_recipe=None, level=1):
    obj = dict(id=oid, type=kind, x=x, y=y, w=2, h=2, revision=0, level=level, jobs=[], animal=animal, animal_job=None)
    if last_recipe:
        obj.update(last_recipe=last_recipe, recipes_memory=[last_recipe], recipe_cursor=0)   # already migrated
    state['objects'].append(obj)
    return obj


def obj(state, oid):
    return next(o for o in state['objects'] if o['id'] == oid)


def hire_and_start(state, helper, plan='night', zone=None, at=T0):
    cmd(state, 'hire_helper', {'helper': helper}, at)
    if zone:
        cmd(state, 'set_zone', {'worker': helper, 'zone': zone}, at)
    cmd(state, 'start_shift', {'worker': helper, 'shift': plan}, at)
    return state['helpers'][helper]


def core(state):
    """The farm without its (frequency dependent) journal and the r8 market clock (a caravan starts when first seen)."""
    return {k: v for k, v in state.items() if k not in {'events', 'market'}}


def left(width=10):
    return dict(x=0, y=0, w=width, h=20)


def right(width=10):
    return dict(x=20 - width, y=0, w=width, h=20)


# --- catalog ---------------------------------------------------------------------------------------

def test_catalog_validates_version_bumped_and_new_rows_are_additive():
    validate()
    assert VERSION in {'farm-2026-10-r7', 'farm-2026-10-r8', 'farm-2026-10-r9'}
    for hid in NEW_HELPERS:
        h = HELPERS[hid]
        assert h['role'] in {'harvest', 'animals', 'craft'} and h['id'] == hid and h['cost'] > 0
    assert HELPERS['shepherd']['role'] == 'animals' and HELPERS['raccoon']['role'] == 'production'
    assert EQUIPMENT['harvester']['role'] == 'reap' and 'harvester' not in HELPERS  # id must not clash
    assert public_catalog()['automation']['plot_limits'][20] == 120
    assert {'short', 'day', 'night', 'estate', 'manor'} <= set(SHIFTS)
    # old rows are untouched
    assert (SHIFTS['night']['actions'], SHIFTS['night']['cost']) == (96, 22) and HELPERS['shepherd']['cost'] == 110


def test_every_helper_has_an_icon_and_a_figure():
    icons = (STATIC / 'icons.svg').read_text(encoding='utf-8')
    scene = (STATIC / 'scene_expansion.js').read_text(encoding='utf-8')
    for hid, h in HELPERS.items():
        assert f'id="{h["icon"]}"' in icons, h['icon']
        assert hid in scene, hid


def test_client_uses_the_new_commands_and_draws_zones():
    app = (STATIC / 'app.js').read_text(encoding='utf-8')
    for word in ('collect_group', 'feed_all', 'restart_all', 'plant_many', 'set_zone'):
        assert f"'{word}'" in app, word
    assert 'zones' in (STATIC / 'scene_expansion.js').read_text(encoding='utf-8')


# --- balance ---------------------------------------------------------------------------------------

def test_wage_is_a_small_fraction_of_the_value_of_one_action():
    cheapest = min(c['price'] * c['yield_qty'] for c in CROPS.values())
    per_action = {k: p['cost'] / p['actions'] for k, p in SHIFTS.items()}
    for key, wage in per_action.items():
        assert 0.15 <= wage <= 0.4, key        # not free, not a tax
        assert wage <= cheapest * 0.07, key    # a wheat harvest is worth far more than the wage
        assert SHIFTS[key]['actions'] <= SHIFTS[key]['seconds'] / 30  # never faster than one action per 30 s
    assert per_action['estate'] < per_action['night'] and per_action['manor'] <= per_action['estate']
    assert max(p['seconds'] for p in SHIFTS.values()) == 28800 and all(p['cost'] <= 100 for p in SHIFTS.values())


def test_helper_output_equals_manual_output_so_net_value_is_lower_by_the_wage():
    manual, auto = farm(), farm()
    for st in (manual, auto):
        add_plots(st, 30)
    cmd(manual, 'collect_group', {'group': 'plots', 'area': None})
    spent = auto['coins']
    hire_and_start(auto, 'fox_picker', 'day')
    wage = spent - auto['coins']
    settle(auto, T0 + 7200)
    assert wage == HELPERS['fox_picker']['cost'] + SHIFTS['day']['cost']
    for key in ('inventory', 'xp'):
        assert auto[key] == manual[key]
    assert auto['stats']['harvests'] == manual['stats']['harvests'] == 30
    assert auto['coins'] == manual['coins'] - wage < manual['coins']  # saves taps, never adds income


def test_helper_pace_never_exceeds_one_action_per_thirty_seconds():
    st = farm()
    add_plots(st, 100)
    hire_and_start(st, 'fox_picker', 'manor')
    settle(st, T0 + 30 * 10)
    assert st['helpers']['fox_picker']['shift']['done'] == 11  # at 0, 30, ... 300
    assert st['stats']['harvests'] == 11


# --- harvest role and zones -----------------------------------------------------------------------

def test_harvester_works_only_inside_its_zone():
    st = farm()
    add_plots(st, 60)  # three rows of 20: x 0..19
    hire_and_start(st, 'fox_picker', 'day', zone=left())
    settle(st, T0 + 7200)
    shift = st['helpers']['fox_picker']['shift']
    assert shift['done'] == 30 and shift['status'] == 'finished'
    assert all(o['crop'] is None for o in st['objects'] if o['x'] < 10)
    assert all(o['crop'] for o in st['objects'] if o['x'] >= 10)
    assert st['inventory']['wheat'] == 30 * 3 and st['stats']['harvests'] == 30


def test_two_harvesters_cover_two_zones_and_one_whole_farm_without_zone():
    st = farm()
    add_plots(st, 60)
    hire_and_start(st, 'fox_picker', 'day', zone=left())
    hire_and_start(st, 'hamster_reaper', 'day', zone=right())
    settle(st, T0 + 7200)
    assert all(o['crop'] is None for o in st['objects'])
    assert st['helpers']['fox_picker']['shift']['done'] == st['helpers']['hamster_reaper']['shift']['done'] == 30
    whole = farm()
    add_plots(whole, 20)
    hire_and_start(whole, 'fox_picker', 'day')  # no zone = the whole farm
    settle(whole, T0 + 7200)
    assert all(o['crop'] is None for o in whole['objects'])


def test_catch_up_after_long_offline_harvests_each_bed_after_it_is_ripe_and_is_idempotent():
    def build():
        st = farm()
        for i in range(20):  # ripens every 10 minutes over ~3.3 hours
            add_plots(st, 1, ready_at=T0 + 600 * i, x0=i, prefix='q')
        hire_and_start(st, 'fox_picker', 'night')
        return st
    one, two, three = build(), build(), build()
    end = T0 + 10 * 3600  # the player was away longer than the paid shift
    settle(one, end)
    settle(two, T0 + 5000)
    settle(two, T0 + 20000)
    settle(two, end)
    settle(three, end)
    settle(three, end)  # a second settle at the same instant changes nothing
    assert core(one) == core(two) == core(three)
    shift = one['helpers']['fox_picker']['shift']
    assert shift['status'] == 'finished' and shift['done'] == 20 and shift['ended_at'] == T0 + 28800
    assert all(o['crop'] is None for o in one['objects']) and one['xp'] == LEVELS[29] + 20 * CROPS['wheat']['xp']


def test_no_work_after_the_paid_deadline():
    st = farm()
    add_plots(st, 5, ready_at=T0 + 4000)  # ripens only after the half-hour shift is over
    hire_and_start(st, 'fox_picker', 'short')
    settle(st, T0 + 3 * 86400)
    shift = st['helpers']['fox_picker']['shift']
    assert shift['status'] == 'finished' and shift['done'] == 0 and all(o['crop'] for o in st['objects'])


def test_quota_exhaustion_stops_the_shift_and_leaves_the_rest_ripe():
    st = farm()
    add_plots(st, 40)
    hire_and_start(st, 'fox_picker', 'short')
    settle(st, T0 + 1800)
    shift = st['helpers']['fox_picker']['shift']
    assert shift['done'] == 12 and shift['remaining'] == 0 and shift['status'] == 'finished'
    assert sum(1 for o in st['objects'] if o['crop']) == 28 and shift['ended_at'] < shift['until']
    settle(st, T0 + 86400)
    assert sum(1 for o in st['objects'] if o['crop']) == 28  # no automatic renewal


def test_big_plans_need_the_farm_level():
    st = farm(xp=LEVELS[4])
    st['helpers']['fox_picker'] = dict(acquired_at=0, shift=None, total_runs=0)
    assert err(st, 'start_shift', {'worker': 'fox_picker', 'shift': 'estate'}) == 'locked'
    assert err(st, 'start_shift', {'worker': 'fox_picker', 'shift': 'manor'}) == 'locked'
    st['xp'] = LEVELS[7]
    cmd(st, 'start_shift', {'worker': 'fox_picker', 'shift': 'estate'})
    assert st['helpers']['fox_picker']['shift']['quota'] == 240
    validate_state(st)


def test_cannot_start_a_shift_without_coins_or_for_a_helper_who_is_not_hired():
    st = farm(coins=HELPERS['fox_picker']['cost'] + 3)
    cmd(st, 'hire_helper', {'helper': 'fox_picker'})
    assert err(st, 'start_shift', {'worker': 'fox_picker', 'shift': 'short'}) == 'insufficient_coins'
    assert err(st, 'start_shift', {'worker': 'cat_keeper', 'shift': 'short'}) == 'not_hired'


# --- zones as a command --------------------------------------------------------------------------

def test_set_zone_validation_and_clearing():
    st = farm()
    cmd(st, 'hire_helper', {'helper': 'fox_picker'})
    assert err(st, 'set_zone', {'worker': 'cat_keeper', 'zone': None}) == 'not_hired'
    for bad in ({'x': -1, 'y': 0, 'w': 3, 'h': 3}, {'x': 58, 'y': 0, 'w': 3, 'h': 3}, {'x': 0, 'y': 0, 'w': 0, 'h': 3},
                {'x': 0, 'y': 0, 'w': 3}, {'x': 0, 'y': 0, 'w': 3, 'h': 3.0}, {'x': True, 'y': 0, 'w': 3, 'h': 3}, [1, 2], 'all'):
        assert err(st, 'set_zone', {'worker': 'fox_picker', 'zone': bad}) in {'invalid_zone', 'invalid_command'}
    cmd(st, 'set_zone', {'worker': 'fox_picker', 'zone': dict(x=2, y=3, w=4, h=5)})
    assert st['helpers']['fox_picker']['zone'] == dict(x=2, y=3, w=4, h=5)
    cmd(st, 'set_zone', {'worker': 'fox_picker', 'zone': None})
    assert 'zone' not in st['helpers']['fox_picker']
    cmd(st, 'hire_helper', {'helper': 'hedgehog'})
    assert err(st, 'set_zone', {'worker': 'hedgehog', 'zone': None}) == 'guide'
    assert err(st, 'set_zone', {'worker': 'fox_picker'}) == 'invalid_command'


def test_changing_the_zone_mid_shift_does_not_rewrite_history():
    st = farm()
    add_plots(st, 60)
    hire_and_start(st, 'fox_picker', 'day', zone=left())
    settle(st, T0 + 15 * 30 - 1)  # 15 actions: the whole left half (30 beds) takes 30
    cmd(st, 'set_zone', {'worker': 'fox_picker', 'zone': right()}, T0 + 15 * 30 - 1)
    done_left = sum(1 for o in st['objects'] if o['x'] < 10 and not o['crop'])
    assert done_left == 15
    settle(st, T0 + 7200)
    assert sum(1 for o in st['objects'] if o['x'] < 10 and not o['crop']) == 15  # left half stays as it was
    # the quota (36) still counts the 15 left-half actions: 21 right-half beds remain to be picked
    assert sum(1 for o in st['objects'] if o['x'] >= 10 and not o['crop']) == 21


def test_robot_also_accepts_a_zone():
    st = farm()
    add_plots(st, 40)
    cmd(st, 'buy_equipment', {'equipment': 'robot'})
    cmd(st, 'set_zone', {'worker': 'robot', 'zone': left(5)})
    cmd(st, 'start_shift', {'worker': 'robot', 'shift': 'day'})
    settle(st, T0 + 7200)
    assert all(o['crop'] is None for o in st['objects'] if o['x'] < 5)
    assert all(o['crop'] for o in st['objects'] if o['x'] >= 5)


# --- feeder ---------------------------------------------------------------------------------------

def coops(st, n, x0=0):
    for i in range(n):
        add_building(st, 'coop', f'coop{i}', x0 + (i % 5) * 2, (i // 5) * 2 + 10, animal='chicken')


def test_feeder_feeds_and_collects_inside_its_zone_only():
    st = farm()
    coops(st, 10)  # x 0..9 in five columns, y 10..13
    st['inventory'] = {'feed': 100}
    zone = dict(x=0, y=10, w=10, h=2)  # first row of five coops
    hire_and_start(st, 'cat_keeper', 'night', zone=zone)
    settle(st, T0 + 8 * 3600)
    first, second = [obj(st, f'coop{i}') for i in range(5)], [obj(st, f'coop{i}') for i in range(5, 10)]
    assert all(o['revision'] > 0 for o in first) and all(o['revision'] == 0 for o in second)
    shift = st['helpers']['cat_keeper']['shift']
    feeds = 100 - st['inventory']['feed']
    assert feeds > 0 and shift['done'] >= feeds and st['inventory'].get('egg', 0) >= 2 * (feeds - 5)


def test_feeder_waits_without_feed_and_does_not_spend_quota():
    st = farm()
    coops(st, 3)
    hire_and_start(st, 'cat_keeper', 'day')
    settle(st, T0 + 7200)
    shift = st['helpers']['cat_keeper']['shift']
    assert shift['done'] == 0 and shift['remaining'] == 36 and shift['status'] == 'finished'
    assert all(o['animal_job'] is None for o in st['objects'])


def test_feeder_scales_with_house_level():
    st = farm()
    add_building(st, 'coop', 'c', 0, 0, animal='chicken', level=3)
    st['inventory'] = {'feed': 9}
    hire_and_start(st, 'shepherd', 'short')
    settle(st, T0 + 60)
    assert st['inventory']['feed'] == 6 and obj(st, 'c')['animal_job']['outputs'] == {'egg': 6}


# --- artisan --------------------------------------------------------------------------------------

def test_artisan_collects_and_restarts_the_remembered_recipe_until_inputs_run_out():
    st = farm()
    add_building(st, 'mill', 'm', 0, 0, last_recipe='flour')
    st['inventory'] = {'wheat': 10}
    hire_and_start(st, 'beaver_artisan', 'day')
    settle(st, T0 + 7200)
    assert st['inventory'] == {'wheat': 0, 'flour': 5}
    assert obj(st, 'm')['jobs'] == [] and st['stats']['crafts'] == 5
    shift = st['helpers']['beaver_artisan']['shift']
    assert shift['done'] == 10 and shift['status'] == 'finished'  # 3 starts (queue) + 2 collect-and-restart (2 units each) + 3 final collections


def test_artisan_needs_a_remembered_recipe_and_enough_inputs_and_respects_the_queue():
    st = farm()
    add_building(st, 'mill', 'old', 0, 0)  # old save: nothing remembered
    add_building(st, 'mill', 'poor', 4, 0, last_recipe='flour')
    st['inventory'] = {'wheat': 1}
    hire_and_start(st, 'beaver_artisan', 'day')
    settle(st, T0 + 7200)
    assert st['inventory'] == {'wheat': 1} and all(not o['jobs'] for o in st['objects'])
    assert st['helpers']['beaver_artisan']['shift']['done'] == 0
    full = farm()
    mill = add_building(full, 'mill', 'm', 0, 0, last_recipe='flour')
    full['inventory'] = {'wheat': 100}
    hire_and_start(full, 'beaver_artisan', 'short')
    settle(full, T0 + 61)
    assert len(mill['jobs']) <= 3  # level 1 queue
    assert len({j['id'] for j in mill['jobs']}) == len(mill['jobs'])


def test_manual_queue_remembers_the_recipe_and_it_drives_the_artisan_in_its_zone_only():
    st = farm()
    add_building(st, 'mill', 'a', 0, 0)
    add_building(st, 'mill', 'b', 12, 0)
    st['inventory'] = {'wheat': 4}  # exactly the two manual batches: nothing left for a restart
    for oid in ('a', 'b'):
        cmd(st, 'queue', {'object': oid, 'recipe': 'flour'})
        assert obj(st, oid)['last_recipe'] == 'flour'
    hire_and_start(st, 'badger_artisan', 'day', zone=left(6))
    settle(st, T0 + 7200)
    assert obj(st, 'a')['jobs'] == [] and len(obj(st, 'b')['jobs']) == 1  # b is outside the zone: not collected
    assert st['inventory']['flour'] == 1


def test_artisan_equals_manual_play():
    manual, auto = farm(), farm()
    for st in (manual, auto):
        add_building(st, 'mill', 'm', 0, 0, last_recipe='flour')
        st['inventory'] = {'wheat': 6}
    for i in range(3):
        cmd(manual, 'queue', {'object': 'm', 'recipe': 'flour'}, T0 + i)
    for job in list(obj(manual, 'm')['jobs']):
        cmd(manual, 'collect', {'object': 'm', 'job': job['id']}, T0 + 7200)
    spent = auto['coins']
    hire_and_start(auto, 'beaver_artisan', 'day')
    wage = spent - auto['coins']
    settle(auto, T0 + 7200)
    assert auto['inventory'] == manual['inventory'] and auto['xp'] == manual['xp']
    assert auto['coins'] == manual['coins'] - wage


# --- bulk collect ---------------------------------------------------------------------------------

def mixed_farm():
    st = farm()
    add_plots(st, 30)
    add_plots(st, 5, ready_at=T0 + 5000, x0=0, y0=7, prefix='g')  # still growing
    coops(st, 4)
    for o in st['objects']:
        if o['type'] == 'coop':
            o['animal_job'] = dict(ready_at=T0 - 1, outputs={'egg': 2}, version=VERSION)
    add_building(st, 'mill', 'm1', 0, 16)
    add_building(st, 'mill', 'm2', 12, 16)
    for oid, outputs in (('m1', {'flour': 1}), ('m2', {'flour': 1})):
        obj(st, oid)['jobs'] = [dict(id=f'j{oid}', recipe='flour', starts_at=T0 - 60, ready_at=T0 - 1, seconds=60,
                                     inputs={'wheat': 2}, outputs=outputs, xp=4, version=VERSION),
                                dict(id=f'k{oid}', recipe='flour', starts_at=T0, ready_at=T0 + 900, seconds=900,
                                     inputs={'wheat': 2}, outputs=outputs, xp=4, version=VERSION)]
    return st


def test_collect_group_per_category_matches_single_actions():
    st = mixed_farm()
    cmd(st, 'collect_group', {'group': 'plots', 'area': None})
    assert st['inventory']['wheat'] == 90 and st['stats']['harvests'] == 30
    assert sum(1 for o in st['objects'] if o['type'] == 'plot' and o['crop']) == 5  # growing ones stay
    assert err(st, 'collect_group', {'group': 'plots', 'area': None}) == 'nothing_ready'
    cmd(st, 'collect_group', {'group': 'animals', 'area': None})
    assert st['inventory']['egg'] == 8 and all(o.get('animal_job') is None for o in st['objects'])
    cmd(st, 'collect_group', {'group': 'workshops', 'area': None})
    assert st['inventory']['flour'] == 2 and all(len(o['jobs']) == 1 for o in st['objects'] if o['type'] == 'mill')
    assert err(st, 'collect_group', {'group': 'workshops', 'area': None}) == 'nothing_ready'
    validate_state(st)


def test_collect_group_respects_area_and_rejects_bad_input():
    st = mixed_farm()
    cmd(st, 'collect_group', {'group': 'workshops', 'area': dict(x=0, y=15, w=6, h=5)})
    assert st['inventory']['flour'] == 1 and obj(st, 'm2')['jobs'][0]['id'] == 'jm2'
    assert err(st, 'collect_group', {'group': 'cows', 'area': None}) == 'invalid_command'
    assert err(st, 'collect_group', {'group': 'plots', 'area': dict(x=0, y=0, w=99, h=1)}) == 'invalid_area'
    assert err(st, 'collect_group', {'group': 'plots'}) == 'invalid_command'


def test_old_collect_all_is_unchanged():
    st = mixed_farm()
    cmd(st, 'collect_all', {})
    assert st['stats']['harvests'] == 30


# --- feed_all / restart_all ---------------------------------------------------------------------

def test_feed_all_is_partial_when_feed_is_short_and_fails_when_nothing_can_be_done():
    st = farm()
    coops(st, 6)
    assert err(st, 'feed_all', {'area': None}) == 'nothing_to_do'
    st['inventory'] = {'feed': 4}
    text = cmd(st, 'feed_all', {'area': None})
    assert sum(1 for o in st['objects'] if o['animal_job']) == 4 and st['inventory']['feed'] == 0 and '2' in text
    assert err(st, 'feed_all', {'area': None}) == 'nothing_to_do'


def test_restart_all_repeats_every_remembered_recipe_while_inputs_last():
    st = farm()
    for i in range(3):
        add_building(st, 'mill', f'm{i}', i * 3, 0, last_recipe='flour')
    add_building(st, 'mill', 'fresh', 0, 5)
    st['inventory'] = {'wheat': 5}
    cmd(st, 'restart_all', {'area': None})
    assert sum(len(o['jobs']) for o in st['objects']) == 2 and st['inventory']['wheat'] == 1
    assert err(st, 'restart_all', {'area': None}) == 'nothing_to_do'
    ids = [j['id'] for o in st['objects'] for j in o['jobs']]
    assert len(set(ids)) == len(ids)


# --- mass planting -------------------------------------------------------------------------------

def test_plant_many_plants_every_empty_bed_and_charges_seeds_exactly():
    st = farm(coins=1000)
    add_plots(st, 40, ready_at=None)
    add_plots(st, 5, ready_at=T0 + 100, y0=5, prefix='busy')
    cmd(st, 'plant_many', {'crop': 'wheat', 'area': None})
    assert st['coins'] == 1000 - 40 * CROPS['wheat']['cost']
    assert sum(1 for o in st['objects'] if o['crop']) == 45
    assert all(o['crop']['ready_at'] == T0 + CROPS['wheat']['seconds'] for o in st['objects'] if o['id'].startswith('p'))
    assert err(st, 'plant_many', {'crop': 'wheat', 'area': None}) == 'no_empty_plots'


def test_plant_many_is_partial_when_coins_run_short_in_a_fixed_order():
    st = farm(coins=2 * 7 + 1)
    add_plots(st, 20, ready_at=None, width=10)
    text = cmd(st, 'plant_many', {'crop': 'wheat', 'area': None})
    planted = [o for o in st['objects'] if o['crop']]
    assert len(planted) == 7 and st['coins'] == 1 and 'не на все' in text
    assert {(o['x'], o['y']) for o in planted} == {(x, 0) for x in range(7)}  # top row first, left to right
    st['coins'] = 1
    assert err(st, 'plant_many', {'crop': 'wheat', 'area': None}) == 'insufficient_coins'


def test_plant_many_area_level_and_starter_credit():
    st = farm(coins=500)
    add_plots(st, 40, ready_at=None)
    cmd(st, 'plant_many', {'crop': 'wheat', 'area': dict(x=0, y=0, w=5, h=2)})
    assert sum(1 for o in st['objects'] if o['crop']) == 10 and all(o['x'] < 5 and o['y'] < 2 for o in st['objects'] if o['crop'])
    low = farm(coins=500, xp=0)
    add_plots(low, 3, ready_at=None)
    top = max(CROPS.values(), key=lambda c: c['level'])
    assert err(low, 'plant_many', {'crop': top['id'], 'area': None}) == 'locked'
    assert err(low, 'plant_many', {'crop': 'nope', 'area': None}) == 'unknown_item'
    credit = farm(coins=100)
    credit['starter_credit'] = 100
    add_plots(credit, 4, ready_at=None)
    cmd(credit, 'plant_many', {'crop': 'wheat', 'area': None})
    assert credit['coins'] == 92 and credit['starter_credit'] == 92  # same rule as planting one bed at a time


def test_plant_many_equals_single_plantings():
    one, many = farm(), farm()
    for st in (one, many):
        add_plots(st, 12, ready_at=None)
    for o in list(one['objects']):
        cmd(one, 'plant', {'object': o['id'], 'crop': 'carrot', 'revision': o['revision']})
    cmd(many, 'plant_many', {'crop': 'carrot', 'area': None})
    assert one['coins'] == many['coins']
    strip = lambda st: [{k: v for k, v in o['crop'].items() if k != 'watered'} for o in st['objects']]
    assert strip(one) == strip(many)


# --- bigger land -----------------------------------------------------------------------------------

def test_beds_can_be_built_on_the_far_side_of_a_big_farm():
    st = farm(size=20)
    cmd(st, 'build', {'type': 'plot', 'x': 19, 'y': 19})
    cmd(st, 'build', {'type': 'plot', 'x': 15, 'y': 3})
    assert err(st, 'build', {'type': 'plot', 'x': 20, 'y': 3}) == 'outside_land'   # past the fence, still buyable land
    assert err(st, 'build', {'type': 'plot', 'x': 60, 'y': 3}) == 'invalid_number'  # past the technical ceiling
    small = farm(size=8)
    assert err(small, 'build', {'type': 'plot', 'x': 15, 'y': 3}) == 'outside_land'


def test_plot_and_object_limits_grow_with_the_land_and_the_start_value_is_unchanged():
    assert PLOT_LIMITS[8] == 24 and OBJECT_LIMITS[8] == 80
    assert list(PLOT_LIMITS.values()) == sorted(PLOT_LIMITS.values()) and PLOT_LIMITS[20] == 120
    small = farm(size=8)
    add_plots(small, 24, width=8)
    assert err(small, 'build', {'type': 'plot', 'x': 0, 'y': 5}) == 'plot_limit'
    big = farm(size=20)
    add_plots(big, 119)
    cmd(big, 'build', {'type': 'plot', 'x': 19, 'y': 19})
    assert sum(o['type'] == 'plot' for o in big['objects']) == 120
    assert err(big, 'build', {'type': 'plot', 'x': 18, 'y': 19}) == 'plot_limit'
    validate_state(big)


# --- old saves, projection, scale ----------------------------------------------------------------

def test_old_r6_save_with_a_running_shift_loads_and_settles_unchanged():
    old = new_farm(str(uuid4()), 'Legacy', T0)
    old['catalog'] = 'farm-2026-10-r6'
    old.update(xp=5000, coins=5000)
    old['helpers'] = {}
    old['helpers']['shepherd'] = dict(acquired_at=0, total_runs=0, shift=dict(
        id='s', status='working', plan='night', starts_at=T0, until=T0 + 28800, next_at=T0, interval=30, remaining=96,
        done=0, speed=1, role='animals', quota=96, version='farm-2026-10-r6'))
    old['inventory']['feed'] = 50
    upgraded = upgrade_state(deepcopy(old))
    assert upgraded['catalog'] == VERSION and all('zone' not in h and 'last_recipe' not in o
                                                  for h in upgraded['helpers'].values() for o in upgraded['objects'])
    settle(upgraded, T0 + 28800)
    validate_state(upgraded)
    assert upgraded['helpers']['shepherd']['shift']['done'] > 0 and upgraded['inventory']['egg'] > 0
    assert upgrade_state(deepcopy(upgraded)) == upgraded


def test_a_neighbour_sees_neither_zones_nor_remembered_recipes():
    me, other = farm(fid='00000000-0000-0000-0000-00000000f002'), farm()
    other['settings']['visibility'] = 'public'
    add_building(other, 'mill', 'm', 0, 0, last_recipe='flour')
    hire_and_start(other, 'fox_picker', 'day', zone=left())
    view = project(other, me, T0)
    assert 'last_recipe' not in view['objects'][0] and view['helpers'] == {'fox_picker': {'active': True}}
    assert 'last_recipe' in project(other, other, T0)['objects'][0]


def test_big_farm_with_every_worker_on_a_long_shift_settles_quickly_and_consistently():
    def build():
        st = farm()
        for i in range(100):
            add_plots(st, 1, ready_at=T0 + (i * 211) % 20000, x0=i % 20, y0=i // 20, prefix='b')
        coops(st, 10, x0=0)
        for i in range(8):
            add_building(st, 'mill', f'mill{i}', (i % 5) * 2 + 10, 14 + (i // 5) * 2, last_recipe='feed')
        st['inventory'] = {'wheat': 400, 'feed': 100}
        cmd(st, 'buy_equipment', {'equipment': 'robot'})
        cmd(st, 'start_shift', {'worker': 'robot', 'shift': 'manor'})
        for hid, h in HELPERS.items():
            if h['role'] != 'guide':
                hire_and_start(st, hid, 'manor')
        return st
    st = build()
    started = time.perf_counter()
    settle(st, T0 + 8 * 3600)
    elapsed = time.perf_counter() - started
    assert elapsed < 12, elapsed
    validate_state(st)
    assert st['stats']['automation'] > 100
    assert all(o['crop'] is None for o in st['objects'] if o['type'] == 'plot')
    again = build()
    settle(again, T0 + 3600)
    settle(again, T0 + 5 * 3600)
    settle(again, T0 + 8 * 3600)
    assert core(again) == core(st)  # the chronological result does not depend on how often the farm was opened


def test_every_hired_worker_can_be_stopped_and_work_done_is_kept():
    st = farm()
    add_plots(st, 10)
    hire_and_start(st, 'fox_picker', 'day')
    settle(st, T0 + 90)
    cmd(st, 'stop_shift', {'worker': 'fox_picker'}, T0 + 90)
    done = st['helpers']['fox_picker']['shift']['done']
    settle(st, T0 + 7200)
    assert st['helpers']['fox_picker']['shift']['status'] == 'stopped' and st['helpers']['fox_picker']['shift']['done'] == done
    assert sum(1 for o in st['objects'] if o['crop']) == 10 - done


def test_catalog_items_used_by_tests_exist():
    assert 'flour' in ITEMS and 'feed' in ITEMS and RECIPES['flour']['building'] == 'mill'
