"""Manual plantation replay, persistence and rewards."""
from copy import deepcopy
import json

import pytest

from qw_farm import economy, plantation_game, plantations, progression
from qw_farm.domain import apply, project, validate_state
from tests.test_farm_plantations import cmd, error, farm, T0


def walk(start, end):
    x, y = start % 8, start // 8
    dx, dy = end % 8 - x, end // 8 - y
    return 'R' * dx + 'L' * -dx + 'D' * dy + 'U' * -dy


def route(cells, start=0):
    path = ''
    for cell in cells:
        path += walk(start, cell) + 'C'
        start = cell
    return path


def ready_hectare(crop='vineyard'):
    state = farm()
    cmd(state, 'buy_plantation', {'step': 1})
    cmd(state, 'plant_plantation', dict(plantation=1, revision=0, crop=crop))
    return state, state['plantations'][0]


def start(state, hectare, at, key, op='harvest'):
    apply(state, state, 'plantation_start', dict(plantation=1, revision=hectare['revision'], op=op), at, key)
    return project(state, state, at)['plantations'][0]['run']


def finish(state, run, path, at):
    return cmd(state, 'plantation_finish', dict(plantation=1, run=run['id'], path=path), at)


def auto(state, hectare):
    cmd(state, 'plantation_auto', dict(plantation=1, revision=hectare['revision']), hectare['cycle']['ready_at'])


def test_stale_expired_and_restarted_runs_remain_bound_to_cycle_and_hectare():
    state, hectare = ready_hectare()
    at = hectare['cycle']['ready_at']
    error('not_ready', start, state, hectare, at - 1, 'harvest-early')
    error('prune_not_ready', start, state, hectare, at, 'prune-early', 'prune')
    run = start(state, hectare, at, 'harvest-start')
    assert run == dict(id='harvest-start', op='harvest', targets=hectare['run']['targets'],
                       expires_at=at + 900, limit=384, capacity=8)
    assert len(run['targets']) == len(set(run['targets'])) == 24 and 0 not in run['targets']
    assert hectare['revision'] == 2
    assert plantations.public_catalog()['manual_work'] is True
    saved = json.loads(json.dumps(state))
    validate_state(saved)
    assert project(saved, saved, at)['plantations'][0]['run'] == run
    visitor = farm()
    state['settings']['visibility'] = 'public'
    assert 'plantations' not in project(state, visitor, at)
    error('not_owner', apply, visitor, state, 'plantation_finish',
          dict(plantation=1, run=run['id'], path='R'), at, 'enemy-harvest')
    error('plantation_run_open', start, state, hectare, at + 1, 'harvest-other')
    assert project(state, state, run['expires_at'])['plantations'][0]['run'] is None
    error('plantation_run_expired', finish, state, run, 'R', run['expires_at'])
    fresh = start(state, hectare, run['expires_at'], 'harvest-restart')
    assert fresh['targets'] == run['targets'] and fresh['id'] != run['id']
    error('stale_plantation_run', finish, state, run, 'R', run['expires_at'])
    cmd(state, 'plantation_auto', dict(plantation=1, revision=hectare['revision']), run['expires_at'])
    error('stale_plantation_run', finish, state, fresh, 'R', run['expires_at'])
    assert hectare['harvests'] == 1 and 'run' not in hectare
    new_cycle = start(state, hectare, hectare['cycle']['ready_at'], 'harvest-uproot')
    cmd(state, 'uproot_plantation', dict(plantation=1, revision=hectare['revision']), hectare['cycle']['ready_at'])
    error('stale_plantation_run', finish, state, new_cycle, 'R', run['expires_at'])
    assert 'run' not in hectare
    validate_state(state)


def test_replay_checks_path_capacity_delivery_misses_and_perfect_quality():
    run = dict(op='harvest', targets=list(range(1, 25)))
    for path in ('', 'R' * 385, 'C', 'X', 'U', 'RX', 'RCC', 'RCBCD'):
        error('invalid_plantation_path', plantation_game.replay, run, path)
    error('invalid_plantation_path', plantation_game.replay, run, route(list(range(1, 10))))
    error('empty_plantation_harvest', plantation_game.replay, run, 'RC')
    error('undelivered_plantation_harvest', plantation_game.replay, run, 'RCLXRRC')
    paths = []
    for start in (1, 9, 17):
        cells = list(range(start, start + 8))
        paths.append(route(cells) + walk(cells[-1], 0) + 'X')
    perfect = ''.join(paths)
    assert plantation_game.replay(run, perfect) == dict(quality=125, penalty=0)
    missed = [40, 41, 42, 43, 44]
    assert plantation_game.replay(run, perfect + route(missed)) == dict(quality=105, penalty=20)
    assert plantation_game.replay(run, paths[0] + route(missed)) == dict(quality=85, penalty=20)


def test_manual_harvest_grants_quality_xp_and_penalizes_only_next_actual_collection():
    state, hectare = ready_hectare('tea_garden')
    at = hectare['cycle']['ready_at']
    cycle = deepcopy(hectare['cycle'])
    run = start(state, hectare, at, 'tea-manual')
    ripe = run['targets'][0]
    wrong = next(cell for cell in range(1, 64) if cell not in run['targets'])
    path = route([ripe, wrong]) + walk(wrong, 0) + 'X'
    qty, xp = plantations.cycle_reward(cycle, 85)
    expected = deepcopy(state)
    progression.grant_xp(expected, xp, 'harvest', at, True, economy.DAY)
    finish(state, run, path, at)
    assert state['inventory']['tea_leaf'] == qty and state['xp'] == expected['xp']
    assert hectare['harvest_penalty'] == 5 and state['market']['counts']['h:tea_leaf'] == qty
    error('stale_plantation_run', finish, state, run, path, at)
    next_qty, next_xp = plantations.cycle_reward(hectare['cycle'], 90, -5)
    assert next_xp == plantations.cycle_reward(hectare['cycle'], 90)[1]
    auto(state, hectare)
    assert state['inventory']['tea_leaf'] == qty + next_qty and 'harvest_penalty' not in hectare
    regular = plantations.cycle_reward(hectare['cycle'], 90)[0]
    auto(state, hectare)
    assert state['inventory']['tea_leaf'] == qty + next_qty + regular


def test_prune_fails_at_limit_reopens_and_bonuses_next_four_harvests_only():
    state, hectare = ready_hectare('tea_garden')
    for _ in range(4):
        auto(state, hectare)
    at = hectare['cycle']['started_at']
    initial_stock = state['inventory']['tea_leaf']
    initial_xp = state['xp']
    initial_cycle = deepcopy(hectare['cycle'])
    projection = project(state, state, at)['plantations'][0]
    assert projection['prune_ready'] is True and projection['prune_remaining'] == 0
    run = start(state, hectare, at, 'prune-attempt', 'prune')
    assert run['limit'] == 40 and run['capacity'] == 0
    error('invalid_plantation_path', finish, state, run, 'RL' * 20 + 'R', at)
    error('invalid_plantation_path', finish, state, run, 'X', at)
    finish(state, run, 'RL' * 20, at)
    assert 'pruned_after' not in hectare

    run = start(state, hectare, at, 'prune-success', 'prune')
    targets = sorted(run['targets'], key=lambda cell: (cell // 8, cell % 8 if cell // 8 % 2 == 0 else -(cell % 8)))
    assert len(targets) == 8
    # Six correct cuts are sufficient. A miss subtracts one correct cut from the score.
    missed = next(cell for cell in range(1, 64) if cell not in targets)
    assert plantation_game.replay(run, route(targets[:6])) == dict(success=True)
    assert plantation_game.replay(run, route([missed, *targets[:6]])) == dict(success=False)
    finish(state, run, route(targets), at)
    assert hectare['pruned_after'] == 4 and hectare['cycle'] == initial_cycle
    assert state['xp'] == initial_xp and state['inventory']['tea_leaf'] == initial_stock
    error('prune_not_ready', start, state, hectare, at, 'prune-again-too-early', 'prune')
    for left in (4, 3, 2, 1, 0):
        view = project(state, state, at)['plantations'][0]
        assert view['prune_remaining'] == left and view['prune_ready'] is (left == 0)
        expected = plantations.cycle_reward(hectare['cycle'], 90, 15 if left else 0)
        previous_stock = state['inventory']['tea_leaf']
        at = hectare['cycle']['ready_at']
        auto(state, hectare)
        assert state['inventory']['tea_leaf'] - previous_stock == expected[0]
    validate_state(state)
