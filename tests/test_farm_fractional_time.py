"""Fractional-time class of bugs: wall clocks are float (time.time()), older saves hold float deadlines."""
from copy import deepcopy

import pytest

from qw_farm.catalog import tick
from qw_farm.domain import apply, new_farm, project, validate_state
from qw_farm.expansion import settle, upgrade_state
from tests.test_farm_automation_r7 import T0, farm, add_plots, cmd, hire_and_start

FRAC = 0.8106


def test_tick_floors_to_whole_seconds():
    assert tick(1791653615.810668) == 1791653615 and type(tick(5.9)) is int and tick(7) == 7


def test_settle_accepts_fractional_shift_fields_and_clock():
    state = farm(coins=10 ** 6)
    add_plots(state, 6, ready_at=T0 - 5)
    shift = hire_and_start(state, 'fox_picker', plan='short')['shift']
    # a legacy save: every shift field is a float seconds value
    for key in ('starts_at', 'next_at', 'until'):
        shift[key] = shift[key] + FRAC
    shift['next_at'] = shift['starts_at']
    for now in (T0 + 400, T0 + 400 + FRAC):
        copy = deepcopy(state)
        settle(copy, now)  # used to raise "float object cannot be interpreted as an integer" in range(budget)
        validate_state(copy)
        assert copy['helpers']['fox_picker']['shift']['done'] >= 1
    a, b = deepcopy(state), deepcopy(state)
    settle(a, T0 + 400)
    settle(b, T0 + 400 + FRAC)
    assert a['helpers'] == b['helpers']  # the fraction of the wall clock changes nothing


def test_fractional_commands_store_whole_seconds_and_validate():
    state = upgrade_state(new_farm('00000000-0000-0000-0000-00000000f002', 'Дробь', T0 + FRAC))
    assert state['created_at'] == T0
    state['coins'] = 1000
    apply(state, state, 'plant', dict(object=next(o['id'] for o in state['objects'] if o['type'] == 'plot' and not o['crop']),
                                      crop='wheat', revision=0), T0 + FRAC, 'plant-frac-0001')
    validate_state(state)
    crops = [o['crop'] for o in state['objects'] if o['type'] == 'plot' and o['crop']]
    assert all(type(c['ready_at']) is int and type(c['planted_at']) is int for c in crops)
    assert project(state, state, T0 + FRAC)['server_time'] == T0
