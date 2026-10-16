"""Domain tests for the `rotate` command (building orientation 0/1, stored in the farm payload)."""
from copy import deepcopy
from uuid import uuid4

import pytest

from qw_farm.domain import FarmError, apply, new_farm, project, validate_state
from qw_farm.expansion import upgrade_state


NOW = 1000


def farm(name='Rotate'):
    state = upgrade_state(new_farm(str(uuid4()), name, NOW))
    state.update(coins=5000, xp=5000)
    return state


def put(state, kind='cowshed', oid='target', x=3, y=6, w=2, h=2, **extra):
    obj = dict(id=oid, type=kind, x=x, y=y, w=w, h=h, revision=0, level=1,
               jobs=[], animal=None, animal_job=None)
    obj.update(extra)
    state['objects'].append(obj)
    return obj


def rotate(state, obj, revision=None, other=None):
    return apply(state, other if other is not None else state, 'rotate', {
        'object': obj['id'],
        'revision': obj['revision'] if revision is None else revision,
    }, NOW + 1, str(uuid4()))


def test_rotate_toggles_orientation_and_bumps_revision():
    state = farm()
    obj = put(state)
    assert 'orientation' not in obj  # a missing field means orientation 0

    rotate(state, obj)
    assert obj['orientation'] == 1 and obj['revision'] == 1
    rotate(state, obj)
    assert obj['orientation'] == 0 and obj['revision'] == 2
    validate_state(state)


@pytest.mark.parametrize('kind', ['house', 'barn'])
def test_starting_buildings_can_rotate(kind):
    state = farm()
    obj = next(o for o in state['objects'] if o['type'] == kind)
    rotate(state, obj)
    assert obj['orientation'] == 1


def test_stale_revision_is_rejected_and_state_is_untouched():
    state = farm()
    obj = put(state)
    before = deepcopy(obj)
    with pytest.raises(FarmError) as error:
        rotate(state, obj, revision=5)
    assert error.value.code == 'stale_object'
    assert obj == before


def test_visitor_cannot_rotate_someone_elses_building():
    owner, visitor = farm('Owner'), farm('Visitor')
    obj = put(owner)
    with pytest.raises(FarmError) as error:
        rotate(visitor, obj, other=owner)
    assert error.value.status == 403
    assert 'orientation' not in obj


@pytest.mark.parametrize('kind,extra', [
    ('plot', dict(crop=None, w=1, h=1)),
    ('road', dict(w=1, h=1)),
    ('flowerbed', dict(w=1, h=1)),
    ('duckpond', {}),
])
def test_non_building_objects_are_refused(kind, extra):
    state = farm()
    obj = put(state, kind, **extra)
    with pytest.raises(FarmError) as error:
        rotate(state, obj)
    assert error.value.code == 'cannot_rotate'
    assert 'orientation' not in obj and obj['revision'] == 0


def test_square_building_keeps_footprint():
    state = farm()
    obj = put(state)
    rotate(state, obj)
    assert (obj['x'], obj['y'], obj['w'], obj['h']) == (3, 6, 2, 2)


def test_rectangular_footprint_swaps_when_there_is_room():
    # No catalogue building is rectangular today; the rule must still hold for future ones.
    state = farm()
    obj = put(state, w=2, h=1)
    rotate(state, obj)
    assert (obj['w'], obj['h'], obj['orientation']) == (1, 2, 1)
    rotate(state, obj)
    assert (obj['w'], obj['h'], obj['orientation']) == (2, 1, 0)


def test_rectangular_footprint_blocked_by_neighbour_gives_a_clear_message():
    state = farm()
    obj = put(state, w=2, h=1)
    put(state, 'bench', oid='blocker', x=3, y=7, w=1, h=1)
    with pytest.raises(FarmError) as error:
        rotate(state, obj)
    assert 'места' in error.value.message
    assert (obj['w'], obj['h'], obj.get('orientation', 0), obj['revision']) == (2, 1, 0, 0)


def test_rectangular_footprint_blocked_by_land_edge():
    state = farm()
    edge = state['size'] - 1
    obj = put(state, w=2, h=1, x=edge - 1, y=edge)
    with pytest.raises(FarmError) as error:
        rotate(state, obj)
    assert 'места' in error.value.message
    assert (obj['w'], obj['h']) == (2, 1)


def test_visitors_see_the_orientation_of_a_neighbours_farm():
    owner, visitor = farm('Owner'), farm('Visitor')
    obj = put(owner)
    rotate(owner, obj)
    owner['settings']['visibility'] = 'public'
    seen = project(owner, visitor, NOW + 2)
    assert next(o for o in seen['objects'] if o['id'] == 'target')['orientation'] == 1


@pytest.mark.parametrize('bad', [2, -1, True, '1', None])
def test_validate_state_rejects_invalid_orientation(bad):
    state = farm()
    put(state, orientation=bad)
    with pytest.raises(FarmError):
        validate_state(state)
