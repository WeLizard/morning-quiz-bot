"""Pure-domain regression tests for demolishing farm objects."""
from copy import deepcopy
from uuid import uuid4

import pytest

from qw_farm.domain import FarmError, apply, new_farm
from qw_farm.expansion import upgrade_state


NOW = 1000


def farm(name='Demolish'):
    state = upgrade_state(new_farm(str(uuid4()), name, NOW))
    state.update(coins=5000, xp=5000)
    state['inventory']['wood'] = 10
    return state


def put(state, kind, oid='target', level=1, **extra):
    obj = dict(id=oid, type=kind, x=3, y=6, w=2, h=2, revision=0,
               level=level, jobs=[], animal=None, animal_job=None)
    obj.update(extra)
    state['objects'].append(obj)
    return obj


def demolish(state, obj, revision=None, other=None):
    return apply(state, other if other is not None else state, 'demolish', {
        'object': obj['id'],
        'revision': obj['revision'] if revision is None else revision,
    }, NOW + 1, str(uuid4()))


@pytest.mark.parametrize('kind', ['road', 'flowerbed', 'plot'])
def test_road_decor_and_empty_plot_are_removed_without_refund(kind):
    state = farm()
    obj = put(state, kind, w=1 if kind == 'road' else 2,
              h=1 if kind == 'road' else 2, crop=None if kind == 'plot' else None)
    before_wood = state['inventory'].get('wood', 0)
    before_coins, before_xp = state['coins'], state['xp']

    demolish(state, obj)

    assert obj not in state['objects']
    assert state['inventory'].get('wood', 0) == before_wood
    assert (state['coins'], state['xp']) == (before_coins, before_xp)


@pytest.mark.parametrize(('level', 'wood'), [(1, 4), (3, 6)])
def test_functional_building_returns_level_scaled_wood_without_rewards(level, wood):
    state = farm()
    obj = put(state, 'mill', level=level)
    before_coins, before_xp = state['coins'], state['xp']
    before_wood = state['inventory']['wood']

    demolish(state, obj)

    assert obj not in state['objects']
    assert state['inventory']['wood'] == before_wood + wood
    assert (state['coins'], state['xp']) == (before_coins, before_xp)
    # A new object can occupy the demolished building's footprint.
    apply(state, state, 'build', {'type': 'plot', 'x': obj['x'], 'y': obj['y']},
          NOW + 1, str(uuid4()))
    assert any(o['type'] == 'plot' and (o['x'], o['y']) == (obj['x'], obj['y'])
               for o in state['objects'])


@pytest.mark.parametrize('kind', ['house', 'barn'])
def test_house_and_barn_cannot_be_demolished(kind):
    state = farm()
    obj = put(state, kind)
    before = deepcopy(state)

    with pytest.raises(FarmError):
        demolish(state, obj)

    assert state == before


@pytest.mark.parametrize('busy', ['crop', 'jobs', 'animal_job', 'animal'])
def test_object_with_crop_work_or_animal_cannot_be_demolished(busy):
    state = farm()
    obj = put(state, 'mill')
    if busy == 'crop':
        obj['type'] = 'plot'
        obj['crop'] = {'id': 'wheat', 'ready_at': NOW + 100}
    elif busy == 'jobs':
        obj['jobs'] = [{'id': 'job-1'}]
    elif busy == 'animal_job':
        obj['animal_job'] = {'ready_at': NOW + 100}
    else:
        obj['animal'] = 'chicken'
    before = deepcopy(state)

    with pytest.raises(FarmError):
        demolish(state, obj)

    assert state == before


def test_stale_revision_rejects_demolish_without_state_loss():
    state = farm()
    obj = put(state, 'mill', revision=2)
    before = deepcopy(state)

    with pytest.raises(FarmError):
        demolish(state, obj, revision=1)

    assert state == before


def test_demolish_cannot_target_another_farm():
    owner, other = farm('Owner'), farm('Other')
    obj = put(other, 'mill')
    owner_before, other_before = deepcopy(owner), deepcopy(other)

    with pytest.raises(FarmError):
        demolish(owner, obj, other=other)

    assert owner == owner_before
    assert other == other_before
