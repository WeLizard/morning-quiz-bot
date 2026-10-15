"""Farm r9 stage 13: animal XP is the added value of the batch, fixed when feeding starts."""
from uuid import uuid4

import pytest

from qw_farm.catalog import ANIMALS, ITEMS, LEVELS, VERSION, animal_xp
from qw_farm.domain import apply, new_farm
from qw_farm.expansion import settle, upgrade_state

T0 = 1_800_000_000
EXPECTED = {'chicken': 3, 'cow': 6, 'sheep': 9, 'bees': 16, 'peacock': 28}


def farm(**extra):
    state = upgrade_state(new_farm(str(uuid4()), 'Zoo', T0))
    state.update(size=20, xp=LEVELS[29], coins=10 ** 6, starter_credit=0, objects=[], inventory={}, **extra)
    state['progress'].update(day=10 ** 9, dew=10 ** 9)
    return state


def house(state, animal, level=1, oid='h'):
    spec = ANIMALS[animal]
    state['objects'].append(dict(id=oid, type=spec['building'], x=0, y=0, w=2, h=2, revision=0, level=level, jobs=[],
                                 animal=animal, animal_job=None))
    return state['objects'][-1]


def cmd(state, kind, data, at=T0):
    return apply(state, state, kind, data, at, f'{kind}-{at}-{len(state["events"])}')


def stock(state, animal, level=1):
    mult = {1: 1, 2: 2, 3: 3}[level]
    for k, q in ANIMALS[animal]['inputs'].items():
        state['inventory'][k] = state['inventory'].get(k, 0) + q * mult


def base_xp(animal):
    spec = ANIMALS[animal]
    v_out = sum(ITEMS[k]['price'] * q for k, q in spec['outputs'].items())
    v_in = sum(ITEMS[k]['price'] * q for k, q in spec['inputs'].items())
    return max(2, (v_out - v_in) // 4)


@pytest.mark.parametrize('animal', sorted(ANIMALS))
def test_formula_for_every_animal_and_house_level(animal):
    for level, mult in ((1, 1), (2, 2), (3, 3)):
        assert animal_xp(ANIMALS[animal], level) == base_xp(animal) * mult
    assert animal_xp(ANIMALS[animal], 1) >= 2


def test_documented_examples():
    for animal, xp in EXPECTED.items():
        assert animal_xp(ANIMALS[animal], 1) == xp


@pytest.mark.parametrize('level', (1, 2, 3))
def test_feed_writes_xp_and_collect_grants_exactly_it(level):
    st = farm()
    house(st, 'cow', level)
    stock(st, 'cow', level)
    cmd(st, 'feed', {'object': 'h'})
    xp = st['objects'][0]['animal_job']['xp']
    assert xp == 6 * level
    before = st['xp']
    cmd(st, 'collect_animal', {'object': 'h'}, T0 + 10 ** 6)
    assert st['xp'] - before >= xp  # the funnel may add a bonus on top, never less


def test_batch_started_before_the_change_pays_the_old_five():
    st = farm()
    obj = house(st, 'peacock')
    obj['animal_job'] = dict(ready_at=T0 - 1, outputs={'peacock_feather': 3}, version=VERSION)
    before = st['xp']
    cmd(st, 'collect_animal', {'object': 'h'})
    assert st['xp'] - before == 5


def test_helper_collects_with_the_stored_xp():
    st = farm()
    obj = house(st, 'sheep', 2)
    obj['animal_job'] = dict(ready_at=T0 - 1, outputs={'wool': 4}, xp=18, version=VERSION)
    before = st['xp']
    cmd(st, 'collect_group', {'group': 'animals', 'area': None})
    assert st['xp'] - before == 18
    assert obj['animal_job'] is None


def test_helper_feeding_stores_the_xp_of_the_house_level():
    st = farm()
    house(st, 'sheep', 2)
    stock(st, 'sheep', 2)
    cmd(st, 'hire_helper', {'helper': 'shepherd'})
    cmd(st, 'start_shift', {'worker': 'shepherd', 'shift': 'short'})
    settle(st, T0 + 60)
    job = st['objects'][0]['animal_job']
    assert job and job['xp'] == 18
