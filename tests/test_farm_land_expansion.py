"""Land expansion steps: price, level requirement, maximum and state validation."""
from copy import deepcopy
from uuid import uuid4

import pytest

from qw_farm.catalog import (LAND_MAX, LAND_SIZES, LAND_START, LAND_STEPS, LAND_TABLE, LEVELS, land_bound, land_step, level, object_limit,
                             plot_limit, plot_upkeep, public_catalog)
from qw_farm import economy
from qw_farm.domain import FarmError, apply, new_farm, validate_state
from qw_farm.expansion import upgrade_state


def farm(size=8, xp=10 ** 6, coins=10 ** 8):
    state = upgrade_state(new_farm(str(uuid4()), 'Land', 1000))
    state.update(size=size, xp=xp, coins=coins, starter_credit=0)
    return state


def expand(state):
    return apply(state, state, 'expand', {}, 1000, str(uuid4()))


def test_steps_table_is_consistent():
    sizes = [LAND_START] + [s['size'] for s in LAND_STEPS]
    assert sizes == list(range(8, 61, 2)) and LAND_MAX == 60 == land_bound() and LAND_SIZES == set(sizes)
    assert [(s['size'], s['cost'], s['level']) for s in LAND_STEPS[:6]] == [
        (10, 300, 1), (12, 600, 1), (14, 2500, 6), (16, 6000, 9), (18, 14000, 13), (20, 25000, 18)] and LAND_STEPS[:6] == LAND_TABLE
    assert all(b['cost'] > a['cost'] for a, b in zip(LAND_STEPS, LAND_STEPS[1:]))
    assert all(b['level'] >= a['level'] for a, b in zip(LAND_STEPS, LAND_STEPS[1:]))
    assert LAND_STEPS[-1]['level'] <= len(LEVELS)
    assert public_catalog()['land']['max'] == 60


def test_tail_follows_variant_a():
    """Owner-approved curve (2026-10-14): cost 25000*(s/20)^6 at 3 significant digits, gate 18+5n capped at the last level."""
    tail = {s['size']: s for s in LAND_STEPS}
    assert [(tail[s]['cost'], tail[s]['level']) for s in (22, 24, 26, 28, 30, 32, 40, 60)] == [
        (44300, 23), (74600, 28), (121000, 33), (188000, 38), (285000, 43), (419000, 48), (1600000, 50), (18200000, 50)]
    assert all(s['level'] == min(len(LEVELS), 18 + 5 * (s['size'] - 20) // 2) for s in LAND_STEPS[6:])
    assert all(b['cost'] / a['cost'] < 1.8 for a, b in zip(LAND_STEPS[5:], LAND_STEPS[6:]))   # gentle: no cliff between steps


def test_tail_limits_and_upkeep_have_no_fallback():
    """Silent fallbacks (24 beds, 80 objects, 0 upkeep) must never apply to a valid size."""
    for size in sorted(LAND_SIZES):
        assert plot_limit(size) > 24 or size == 8
        assert object_limit(size) > 80 or size == 8
        assert size < 12 or plot_upkeep(size) > 0
    assert [plot_limit(s) for s in (20, 22, 30, 60)] == [120, 125, 145, 220]
    assert [object_limit(s) for s in (20, 22, 30, 60)] == [200, 233, 400, 1480]
    assert [plot_upkeep(s) for s in (20, 22, 24, 30, 40)] == [30, 36, 43, 68, 120]
    assert all(plot_limit(b) - plot_limit(a) == 5 for a, b in zip(range(20, 60, 2), range(22, 61, 2)))
    assert all(plot_upkeep(b) > plot_upkeep(a) for a, b in zip(range(12, 60, 2), range(14, 61, 2)))


def test_expand_past_old_maximum_and_use_new_land():
    state = farm(20, xp=LEVELS[22], coins=44300)
    expand(state)
    assert state['size'] == 22 and state['coins'] == 0
    state.update(coins=10 ** 6)
    apply(state, state, 'build', {'type': 'plot', 'x': 21, 'y': 21}, 1000, str(uuid4()))
    assert any(o['type'] == 'plot' and (o['x'], o['y']) == (21, 21) for o in state['objects'])
    with pytest.raises(FarmError) as error:
        apply(state, state, 'build', {'type': 'plot', 'x': 22, 'y': 0}, 1000, str(uuid4()))
    assert error.value.code == 'outside_land'
    validate_state(state)


def test_tail_upkeep_is_billed_per_bed():
    state = farm(30)
    beds = sum(o['type'] == 'plot' for o in state['objects'])
    assert beds and economy.base_upkeep(state) >= beds * plot_upkeep(30) == beds * 68


@pytest.mark.parametrize('step', LAND_STEPS, ids=lambda s: str(s['size']))
def test_each_step_charges_price_and_grows_plot(step):
    state = farm(step['size'] - 2)
    before = state['coins']
    expand(state)
    assert state['size'] == step['size'] and before - state['coins'] == step['cost']


@pytest.mark.parametrize('step', [s for s in LAND_STEPS if s['level'] > 1], ids=lambda s: str(s['size']))
def test_step_requires_level(step):
    low = LEVELS[step['level'] - 2]
    state = farm(step['size'] - 2, xp=low)
    assert level(state['xp']) < step['level']
    before = deepcopy(state)
    with pytest.raises(FarmError) as error:
        expand(state)
    assert error.value.code == 'level_required' and state['size'] == before['size'] and state['coins'] == before['coins']
    state['xp'] = LEVELS[step['level'] - 1]
    expand(state)
    assert state['size'] == step['size']


def test_not_enough_coins_and_maximum():
    state = farm(8, coins=299)
    with pytest.raises(FarmError) as error:
        expand(state)
    assert error.value.code == 'insufficient_coins' and state['size'] == 8
    state = farm(60)
    with pytest.raises(FarmError) as error:
        expand(state)
    assert error.value.code == 'max_land' and state['size'] == 60


@pytest.mark.parametrize('size', [0, 7, 9, 11, 13, 21, 23, 61, 62])
def test_invalid_size_is_rejected(size):
    assert land_step(size) is None
    state = farm(size)
    with pytest.raises(FarmError):
        expand(state)
    with pytest.raises(FarmError) as error:
        validate_state(state)
    assert error.value.code == 'invalid_state'


@pytest.mark.parametrize('size', sorted(LAND_SIZES))
def test_every_valid_size_passes_validation(size):
    validate_state(farm(size))
