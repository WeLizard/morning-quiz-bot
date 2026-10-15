"""Pure-domain regression tests for the Farm 0.2.0 rules."""
from copy import deepcopy
from uuid import uuid4

import pytest

from qw_farm.domain import FarmError, apply, new_farm
from qw_farm.expansion import settle, upgrade_state
from qw_farm.catalog import CROPS, HELPERS, SHIFTS


def farm():
    state = upgrade_state(new_farm(str(uuid4()), 'Rules', 1000))
    state['xp'] = 5000
    state['coins'] = 5000
    return state


def command(state, kind, data, at=1000, command_id=None):
    return apply(state, state, kind, data, at, command_id or str(uuid4()))


def test_r1_upgrade_preserves_identity_economy_inventory_crops_and_jobs():
    old = new_farm(str(uuid4()), 'Legacy', 1000)
    old['catalog'] = 'farm-2026-10-r1'
    old['objects'][0]['jobs'] = [dict(
        id='legacy-job', recipe='flour', version='r1', outputs={'flour': 2}, xp=2,
        starts_at=1000, ready_at=6000, inputs={'wheat': 2},
    )]
    before = deepcopy(old)

    upgraded = upgrade_state(old)

    assert upgraded['schema_version'] == 2
    for key in ('id', 'coins', 'inventory', 'objects', 'orders', 'neighbors'):
        assert upgraded[key] == before[key]
    assert upgrade_state(deepcopy(upgraded)) == upgraded


def test_shift_is_bounded_by_time_and_action_quota():
    state = farm()
    state['inventory']['feed'] = 1000
    command(state, 'hire_helper', {'helper': 'shepherd'})
    command(state, 'start_shift', {'worker': 'shepherd', 'shift': 'night'})

    settle(state, 1000 + 10 * 365 * 86400)

    shift = state['helpers']['shepherd']['shift']
    assert shift['status'] == 'finished'
    assert shift['done'] == SHIFTS['night']['actions'] == 96
    assert shift['remaining'] == 0
    assert state['inventory']['egg'] == 96
    assert state['inventory']['feed'] == 952
    assert state['coins'] == 5000 - HELPERS['shepherd']['cost'] - SHIFTS['night']['cost']


def interacting_workers():
    state = farm()
    state['inventory'] = {'wheat': 10}
    for helper in ('raccoon', 'shepherd'):
        command(state, 'hire_helper', {'helper': helper})
        command(state, 'start_shift', {'worker': helper, 'shift': 'night'})
    command(state, 'queue', {'object': 'building_2', 'recipe': 'feed'}, command_id='feed-job')
    return state


def economic_projection(state):
    return {key: deepcopy(state[key]) for key in
            ('inventory', 'coins', 'xp', 'stats', 'objects', 'secrets')}


def test_dependent_workers_recalculate_in_original_event_order():
    state = interacting_workers()

    settle(state, 30000)

    assert state['inventory'].get('egg', 0) == 4
    assert state['inventory'].get('feed', 0) == 0
    assert state['helpers']['raccoon']['shift']['done'] == 1
    assert state['helpers']['shepherd']['shift']['done'] == 4


def test_frequent_and_rare_settlement_produce_same_economy():
    sparse = interacting_workers()
    frequent = deepcopy(sparse)

    for at in range(1000, 30001, 7):
        settle(frequent, at)
    settle(frequent, 30000)
    settle(sparse, 30000)

    assert economic_projection(sparse) == economic_projection(frequent)


def test_commands_reject_client_supplied_rewards():
    state = farm()
    before = deepcopy(state)

    with pytest.raises(FarmError, match='Некорректные параметры'):
        command(state, 'machine_run', {
            'machine': 'tractor', 'crop': 'wheat', 'plots': [], 'replant': False,
            'reward': 999999,
        })

    assert state == before


def test_machine_run_is_applied_to_a_state_copy_and_failure_is_discardable():
    state = farm()
    command(state, 'buy_equipment', {'equipment': 'tractor'})
    before = deepcopy(state)
    plots = [
        {'id': f'plot_{index}', 'revision': 0}
        for index in (3, 4)
    ]
    candidate = deepcopy(state)

    command(candidate, 'machine_run', {
        'machine': 'tractor', 'crop': 'wheat', 'plots': plots, 'replant': False,
    })

    assert state == before
    assert candidate['coins'] == before['coins'] - 2 * CROPS['wheat']['cost']
    assert all(next(o for o in candidate['objects'] if o['id'] == p['id'])['crop']['id'] == 'wheat'
               for p in plots)

    bad_candidate = deepcopy(state)
    with pytest.raises(FarmError):
        command(bad_candidate, 'machine_run', {
            'machine': 'tractor', 'crop': 'wheat',
            'plots': [plots[0], plots[0]], 'replant': False,
        })
    assert state == before
