from copy import deepcopy
from uuid import uuid4

import pytest

from qw_farm import projects
from qw_farm.domain import FarmError, new_farm, project as project_view, validate_state


def _farm():
    return new_farm(str(uuid4()), 'Projects', 1_000)


def _command(farm, kind, stage=0, revision=0, key='lake_pier'):
    data = {'project': key}
    if kind != 'project_select':
        data.update(stage=stage, revision=revision)
    return projects.apply(farm, kind, data)


def test_old_save_gains_projects_without_touching_inventory_or_balance():
    farm = _farm()
    farm.pop('home_projects')
    before_inventory, before_coins = deepcopy(farm['inventory']), farm['coins']

    projects.upgrade_state(farm)

    assert farm['home_projects'] == projects.initial_state()
    assert farm['inventory'] == before_inventory
    assert farm['coins'] == before_coins


def test_project_reserve_release_and_completion_across_stages():
    farm = _farm()
    farm['inventory'].update(wood=6, egg=4, carrot=4)
    _command(farm, 'project_select')

    _command(farm, 'project_reserve', revision=0)
    assert farm['inventory']['wood'] == 0
    assert farm['home_projects']['entries']['lake_pier']['reserved'] == {'wood': 6}

    _command(farm, 'project_release', revision=1)
    assert farm['inventory']['wood'] == 6
    assert farm['home_projects']['entries']['lake_pier']['reserved'] == {}

    _command(farm, 'project_reserve', revision=2)
    assert farm['home_projects']['entries']['lake_pier']['reserved'] == {'wood': 6}
    _command(farm, 'project_deliver', revision=3)
    assert farm['home_projects']['entries']['lake_pier']['stage'] == 1
    assert farm['home_projects']['entries']['lake_pier']['reserved'] == {}

    _command(farm, 'project_reserve', stage=1, revision=4)
    _command(farm, 'project_deliver', stage=1, revision=5)
    assert farm['home_projects']['entries']['lake_pier']['stage'] == 2

    with pytest.raises(FarmError) as error:
        _command(farm, 'project_deliver', stage=1, revision=6)
    assert error.value.code == 'project_finished'
    validate_state(farm)


def test_v1_partial_escrow_keeps_old_recipe_until_delivery():
    farm = _farm()
    state = farm['home_projects']
    state['version'] = 1
    state['active'] = 'lake_pier'
    entry = state['entries']['lake_pier']
    entry['reserved'] = {'wheat': 6}
    farm['inventory']['wheat'] = 0
    original_inventory = deepcopy(farm['inventory'])

    projects.upgrade_state(farm)
    assert state['version'] == projects.initial_state()['version']  # upgrade lands on the current version (3: gazebo stage)
    assert entry['revision'] == 0
    assert entry['legacy_needs'] == {'wheat': 6, 'flour': 2}
    assert projects.effective_needs(state, 'lake_pier', entry) == {'wheat': 6, 'flour': 2}
    assert farm['inventory'] == original_inventory
    assert projects.upgrade_state(farm) is None
    assert entry['reserved'] == {'wheat': 6}

    farm['inventory']['flour'] = 2
    _command(farm, 'project_reserve', revision=0)
    assert entry['reserved'] == {'wheat': 6, 'flour': 2}
    _command(farm, 'project_deliver', revision=1)
    assert entry['stage'] == 1 and 'legacy_needs' not in entry
    assert farm['inventory']['flour'] == 0
    validate_state(farm)


def test_v1_partial_escrow_release_switches_to_wood_and_rejects_stale_command():
    farm = _farm()
    state = farm['home_projects']
    state['version'] = 1
    state['active'] = 'lake_pier'
    entry = state['entries']['lake_pier']
    entry['reserved'] = {'wheat': 3}
    farm['inventory']['wheat'] -= 3
    projects.upgrade_state(farm)

    _command(farm, 'project_release', revision=0)
    assert farm['inventory']['wheat'] == 6
    assert entry == {'stage': 0, 'revision': 1, 'reserved': {}}
    projects.upgrade_state(farm)
    assert entry == {'stage': 0, 'revision': 1, 'reserved': {}}
    assert projects.effective_needs(state, 'lake_pier', entry) == {'wood': 6}
    farm['inventory']['wood'] = 6
    with pytest.raises(FarmError) as error:
        _command(farm, 'project_reserve', revision=0)
    assert error.value.code == 'stale_project'
    _command(farm, 'project_reserve', revision=1)
    assert entry['reserved'] == {'wood': 6}
    validate_state(farm)


def test_v1_empty_stage_changes_recipe_and_revision_but_finished_stage_stays_finished():
    farm = _farm()
    state = farm['home_projects']
    state['version'] = 1
    state['entries']['lake_pier']['revision'] = 8
    state['entries']['tea_arbor']['stage'] = 2
    state['entries']['tea_arbor']['revision'] = 5
    projects.upgrade_state(farm)
    assert state['version'] == projects.initial_state()['version']  # upgrade lands on the current version (3: gazebo stage)
    assert state['entries']['lake_pier'] == {'stage': 0, 'revision': 9, 'reserved': {}}
    assert state['entries']['tea_arbor'] == {'stage': 2, 'revision': 5, 'reserved': {}}
    projects.upgrade_state(farm)
    assert state['entries']['lake_pier']['revision'] == 9
    validate_state(farm)


@pytest.mark.parametrize('bad_reserved', [{'flour': 1}, {'wood': True}, {'wood': 7}])
def test_new_recipe_rejects_invalid_escrow(bad_reserved):
    farm = _farm()
    farm['home_projects']['entries']['lake_pier']['reserved'] = bad_reserved
    with pytest.raises(FarmError) as error:
        projects.validate(farm)
    assert error.value.code == 'invalid_projects'


def test_guest_project_projection_hides_reserved_goods_and_revision():
    farm, visitor = _farm(), _farm()
    farm['settings']['visibility'] = 'public'
    farm['inventory'].update(wood=6)
    _command(farm, 'project_select')
    _command(farm, 'project_reserve')

    view = project_view(farm, visitor, 1_000)
    entry = view['home_projects']['entries']['lake_pier']

    assert view['home_projects']['active'] == 'lake_pier'
    assert entry == {'stage': 0}
    assert 'reserved' not in entry
    assert 'revision' not in entry
    assert 'inventory' not in view

