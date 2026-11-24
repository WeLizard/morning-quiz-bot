"""Plantation mechanics through the farm aggregate and its service."""
import asyncio
from copy import deepcopy
from datetime import datetime
import json
from uuid import uuid4

import pytest

from qw_farm import catalog, economy, plantations, progression
from qw_farm.domain import FarmError, apply, new_farm, project, reachable, validate_state
from qw_farm.service import FarmService, Principal
from tests.test_farm_fields_r9 import MemoryUnit


def moscow(year, month, day):
    return int(datetime(year, month, day, tzinfo=plantations.MOSCOW).timestamp())


T0 = moscow(2026, 10, 1)


def farm(lv=46, coins=3_000_000):
    state = new_farm(str(uuid4()), 'Фермер', T0)
    state.update(xp=catalog.LEVELS[lv - 1], coins=coins, starter_credit=0)
    return state


def cmd(state, kind, data, at=T0, speed=1):
    return apply(state, state, kind, data, at, 'plantation-test', speed)


def error(code, action, *args):
    with pytest.raises(FarmError) as raised:
        action(*args)
    assert raised.value.code == code


def test_disabling_entry_preserves_stock_and_recipes(monkeypatch):
    monkeypatch.setattr(catalog, 'PLANTATIONS_WIRED', False)
    state = farm()
    state['inventory']['tea_leaf'] = 1
    validate_state(json.loads(json.dumps(state)))
    assert 'plantations' not in state
    assert 'plantations' not in project(state, state, T0)
    public = catalog.public_catalog()
    assert 'plantations' not in public and 'tea_factory' in public['buildings']
    assert 'tea_leaf' in public['items'] and 'green_tea' in public['recipes']
    error('unknown_command', cmd, state, 'buy_plantation', {'step': 1})


def test_sequential_purchases_have_stable_ids_and_upkeep():
    state = farm(lv=31)
    error('locked', cmd, state, 'buy_plantation', {'step': 1})
    state = farm(coins=0)
    error('insufficient_coins', cmd, state, 'buy_plantation', {'step': 1})
    assert 'plantations' not in state
    state = farm()
    base = economy.base_upkeep(state)
    error('plantation_step', cmd, state, 'buy_plantation', {'step': 2})
    error('invalid_number', cmd, state, 'buy_plantation', {'step': True})
    before = state['coins']
    for step, ids in [(1, [1]), (2, [1, 2]), (3, [1, 2, 3, 4]), (4, [1, 2, 3, 4, 5, 6])]:
        cmd(state, 'buy_plantation', {'step': step})
        assert [h['id'] for h in state['plantations']] == ids
        assert all(h['crop'] is None for h in state['plantations'])
        assert economy.base_upkeep(state) == base + len(ids) * 1200
        validate_state(state)
    assert before - state['coins'] == sum(s['cost'] for s in plantations.STEPS.values())
    error('already_owned', cmd, state, 'buy_plantation', {'step': 3})
    assert catalog.public_catalog()['plantations']['upkeep'] == 1200
    assert catalog.public_catalog()['plantations']['vineyard_winter_upkeep'] == 600


def test_planting_revision_and_owner_projection():
    state, visitor = farm(), farm()
    state['settings']['visibility'] = 'public'
    error('not_owner', apply, visitor, state, 'buy_plantation', {'step': 1}, T0, 'not-owner')
    cmd(state, 'buy_plantation', {'step': 1})
    data = dict(plantation=1, revision=0, crop='vineyard')
    error('invalid_command', cmd, state, 'plant_plantation', {**data, 'price': 0})
    error('unknown_item', cmd, state, 'plant_plantation', {**data, 'crop': []})
    error('invalid_number', cmd, state, 'plant_plantation', {**data, 'plantation': True})
    before = state['coins']
    cmd(state, 'plant_plantation', data)
    assert state['coins'] == before - 40_000
    assert 'plantations' not in project(state, visitor, T0)
    view = project(state, state, T0)['plantations']
    assert view == [dict(id=1, revision=1, crop='vineyard', harvests=0, state='young',
                         ready_at=T0 + 8 * economy.DAY, run=None, prune_ready=False, prune_remaining=0)]
    assert project(state, state, T0 + 6 * economy.DAY)['plantations'][0]['state'] == 'growing'
    error('stale_object', cmd, state, 'plant_plantation', data)
    error('plantation_occupied', cmd, state, 'plant_plantation', {**data, 'revision': 1})
    cmd(state, 'uproot_plantation', dict(plantation=1, revision=1))
    assert state['coins'] == before - 40_000
    cmd(state, 'plant_plantation', dict(plantation=1, revision=2, crop='tea_garden'))
    assert state['plantations'][0]['revision'] == 3
    assert state['plantations'][0]['cycle']['ready_at'] == T0 + 3 * economy.DAY
    validate_state(json.loads(json.dumps(state)))
    invalid = deepcopy(state)
    invalid['plantations'][0]['id'] = True
    error('invalid_plantations', validate_state, invalid)


def test_winter_boundaries_and_cycle_duration_snapshot():
    grape, tea = (plantations.CULTURES[crop] for crop in ('vineyard', 'tea_garden'))
    winter, spring = moscow(2027, 12, 1), moscow(2028, 3, 1)
    assert plantations.cycle_deadline(grape, winter - 1, 1) == winter
    assert plantations.cycle_deadline(grape, winter - 1, 2) == spring + 1
    assert plantations.cycle_deadline(grape, winter, 1) == spring + 1
    assert plantations.cycle_deadline(grape, spring, 1) == spring + 1
    assert plantations.cycle_deadline(tea, winter, 1) == winter + 1
    state = farm()
    cmd(state, 'buy_plantation', {'step': 1}, winter - 1)
    state['economy']['debt'] = 500
    cmd(state, 'plant_plantation', dict(plantation=1, revision=0, crop='vineyard'), winter - 1, 4)
    cycle = deepcopy(state['plantations'][0]['cycle'])
    assert cycle['active_seconds'] == 207_360
    assert cycle['ready_at'] == spring + 207_359
    state['economy']['debt'] = 0
    assert plantations.owner_view(state, winter)[0]['state'] == 'winter'
    assert plantations.owner_view(state, spring)[0]['state'] == 'young'
    assert state['plantations'][0]['cycle'] == cycle


def test_harvest_waits_and_ages_only_after_collection():
    state = farm()
    winter = moscow(2027, 12, 1)
    planted = winter - 8 * economy.DAY
    cmd(state, 'buy_plantation', {'step': 1}, planted)
    cmd(state, 'plant_plantation', dict(plantation=1, revision=0, crop='vineyard'), planted)
    data = dict(plantation=1, revision=1)
    before = deepcopy(state)
    error('not_ready', cmd, state, 'plantation_auto', data, winter - 1)
    assert state == before
    at = winter + economy.DAY
    assert plantations.owner_view(state, at)[0]['state'] == 'ready'
    state['economy']['billed_day'] = economy.moscow_day(at)
    expected = deepcopy(state)
    progression.grant_xp(expected, 576, 'harvest', at, True, 2 * economy.DAY)
    cmd(state, 'plantation_auto', data, at)
    assert state['coins'] == before['coins'] and state['inventory']['grape'] == 53
    assert state['market']['counts']['h:grape'] == 53
    assert state['xp'] == expected['xp']
    hectare = state['plantations'][0]
    assert hectare['cycle']['started_at'] == at
    assert hectare['cycle']['ready_at'] == moscow(2028, 3, 3)
    for quantity in [53, 53, 88]:
        at = hectare['cycle']['ready_at'] + 1
        stock = state['inventory']['grape']
        cmd(state, 'plantation_auto', dict(plantation=1, revision=hectare['revision']), at)
        assert state['inventory']['grape'] - stock == quantity
        assert hectare['cycle']['ready_at'] == at + 2 * economy.DAY
    assert hectare['harvests'] == 4


def test_tea_enters_order_pool_after_first_collection():
    state = farm()
    winter = moscow(2027, 12, 1)
    cmd(state, 'buy_plantation', {'step': 1}, winter)
    cmd(state, 'plant_plantation', dict(plantation=1, revision=0, crop='tea_garden'), winter)
    assert 'tea_leaf' not in reachable(state)
    deadline = state['plantations'][0]['cycle']['ready_at']
    assert deadline == winter + 3 * economy.DAY
    assert plantations.owner_view(state, winter)[0]['state'] == 'young'
    cmd(state, 'plantation_auto', dict(plantation=1, revision=1), deadline)
    assert state['inventory']['tea_leaf'] == 51 and 'tea_leaf' in reachable(state)
    cmd(state, 'uproot_plantation', dict(plantation=1, revision=2), deadline)
    assert 'tea_leaf' in reachable(state)
    validate_state(state)


def test_current_season_keeps_its_reward_after_rebalance(monkeypatch):
    state = farm()
    cmd(state, 'buy_plantation', {'step': 1})
    grape = plantations.CULTURES['vineyard']
    with monkeypatch.context() as old_catalog:
        old_catalog.setitem(grape, 'yield_qty', 75)
        cmd(state, 'plant_plantation', dict(plantation=1, revision=0, crop='vineyard'))
    hectare = state['plantations'][0]
    cycle = deepcopy(hectare['cycle'])
    assert hectare['cycle'] == cycle and plantations.cycle_reward(cycle) == (41, 576)
    cmd(state, 'plantation_auto', dict(plantation=1, revision=1), cycle['ready_at'])
    assert state['inventory']['grape'] == 41
    assert hectare['cycle']['ready_at'] == cycle['ready_at'] + 2 * economy.DAY
    assert plantations.cycle_reward(hectare['cycle']) == (53, 576)


def test_plantation_processing_uses_standard_workshops():
    public = catalog.public_catalog()
    assert public['buildings']['tea_factory']['level'] == 32
    for item, building, price in [('wine_zero', 'cellar', 273), ('raisin', 'dryer', 230),
                                  ('green_tea', 'tea_factory', 127), ('black_tea', 'tea_factory', 142)]:
        assert public['recipes'][item]['building'] == building
        assert public['items'][item]['price'] == price
    catalog.validate()

    state = farm(lv=32)
    cmd(state, 'buy_plantation', {'step': 1})
    cmd(state, 'plant_plantation', dict(plantation=1, revision=0, crop='tea_garden'))
    cmd(state, 'build', dict(type='tea_factory', x=6, y=6))
    factory = state['objects'][-1]
    assert 'green_tea' not in reachable(state)
    data = dict(object=factory['id'], recipe='green_tea')
    error('missing_goods', cmd, state, 'queue', data)
    at = T0 + 3 * economy.DAY
    cmd(state, 'plantation_auto', dict(plantation=1, revision=1), at)
    assert 'green_tea' in reachable(state)
    cmd(state, 'queue', data, at)
    assert state['inventory']['tea_leaf'] == 46
    job, = factory['jobs']
    cmd(state, 'collect', dict(object=factory['id'], job=job['id']), job['ready_at'])
    assert state['inventory']['green_tea'] == 2
    validate_state(state)


def test_farm_service_replays_and_rejects_stale_tab():
    async def scenario():
        state = farm()
        unit = MemoryUnit('account', state)
        now = [T0]
        service = FarmService(unit, Principal('account', 'Фермер'), clock=lambda: now[0])
        await service.command('land-plantation-1', 'buy_plantation', {'step': 1})
        await service.command('plant-plantation-1', 'plant_plantation', dict(plantation=1, revision=0, crop='vineyard'))
        now[0] += 8 * economy.DAY
        data = dict(plantation=1, revision=1)
        result = await service.command('harvest-plantation-1', 'plantation_auto', data)
        live = unit.farms[state['id']]
        after = deepcopy(live)
        assert await service.command('harvest-plantation-1', 'plantation_auto', data) == result
        with pytest.raises(FarmError) as stale:
            await service.command('harvest-plantation-2', 'plantation_auto', data)
        assert stale.value.code == 'stale_object'
        assert unit.farms[state['id']] == after
        assert live['inventory']['grape'] == 53 and live['plantations'][0]['harvests'] == 1
        assert [k for k, kind in unit.records if kind == 'plantation_auto'] == ['harvest-plantation-1']
    asyncio.run(scenario())
