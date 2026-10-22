"""Feeding the lake swans: grain for a little XP, daily limit, cooldown, privacy and replay."""
import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from qw_farm import swans
from qw_farm.catalog import FISHING_LEVEL, LEVELS, ITEMS
from qw_farm.domain import FarmError, apply, project, validate_state
from qw_farm.expansion import upgrade_state
from qw_farm.persistence import Unit
from qw_farm.progression import moscow_day
from tests.test_farm_automation_r7 import T0, farm
from tests.test_farm_platform import (accepted, command, environment, farm_pg_url, player, raw_farm,
                                      view)

DAY = 86400


def swan_farm(level=FISHING_LEVEL, grain=20):
    state = farm(coins=100, xp=LEVELS[level - 1])
    state['inventory'] = {'wheat': grain}
    return state


def feed(state, at=T0, key=None):
    return apply(state, state, 'feed_swans', {}, at, key or f'swans-{at}-{len(state["events"])}')


def code(state, at=T0):
    with pytest.raises(FarmError) as caught:
        feed(state, at)
    return caught.value.code


def test_feeding_spends_grain_grants_xp_and_records_state():
    state = swan_farm()
    xp = state['xp']
    notice = feed(state)
    assert state['inventory']['wheat'] == 20 - swans.COST
    assert state['xp'] == xp + swans.XP
    assert f'+{swans.XP} опыта' in notice and str(swans.COST) in notice
    assert state['swans'] == dict(day=moscow_day(T0), fed=1, next_at=T0 + swans.COOLDOWN, total=1)
    validate_state(state)


def test_item_is_the_early_grain():
    assert swans.ITEM == 'wheat' and ITEMS['wheat']['name'] == 'Пшеница'


def test_cooldown_then_daily_limit_then_next_moscow_day():
    state = swan_farm()
    feed(state)
    assert code(state, T0 + swans.COOLDOWN - 1) == 'swans_wait'
    at = T0
    for _ in range(swans.DAILY_LIMIT - 1):
        at += swans.COOLDOWN
        feed(state, at)
    assert state['swans']['fed'] == swans.DAILY_LIMIT
    assert code(state, at + swans.COOLDOWN) == 'swans_full'
    next_day = (moscow_day(at) + 1) * DAY - 3 * 3600          # Moscow midnight in UTC seconds
    assert moscow_day(next_day) == moscow_day(at) + 1
    feed(state, max(next_day, at + swans.COOLDOWN))
    assert state['swans']['fed'] == 1 and state['swans']['total'] == swans.DAILY_LIMIT + 1


def test_missing_grain_is_a_clear_error_and_changes_nothing():
    state = swan_farm(grain=swans.COST - 1)
    before = deepcopy(state)
    with pytest.raises(FarmError) as caught:
        feed(state)
    assert caught.value.code == 'missing_goods' and 'Пшеница' in caught.value.message
    assert state['inventory'] == before['inventory'] and state['xp'] == before['xp']


def test_lake_must_be_unlocked():
    state = swan_farm(level=FISHING_LEVEL - 1)
    assert code(state) == 'locked'
    assert swans.public(state, T0)['unlocked'] is False
    assert swans.public(swan_farm(), T0)['unlocked'] is True


def test_command_takes_no_parameters_and_only_the_owner_may_feed():
    state, other = swan_farm(), swan_farm()
    other['id'] = str(uuid4())
    with pytest.raises(FarmError) as caught:
        apply(state, state, 'feed_swans', {'xp': 999}, T0, 'k1')
    assert caught.value.code == 'invalid_command'
    with pytest.raises(FarmError) as caught:
        apply(state, other, 'feed_swans', {}, T0, 'k2')
    assert caught.value.code == 'not_owner'
    assert state['xp'] == LEVELS[FISHING_LEVEL - 1]


def test_old_farm_without_field_gets_defaults_and_public_view_counts_down():
    state = swan_farm()
    del state['swans']
    upgrade_state(state)
    assert state['swans'] == swans.blank()
    validate_state(state)
    pub = swans.public(state, T0)
    assert pub['left'] == swans.DAILY_LIMIT and pub['next_at'] == 0
    feed(state)
    assert swans.public(state, T0 + 1)['left'] == swans.DAILY_LIMIT - 1
    assert swans.public(state, T0 + DAY)['left'] == swans.DAILY_LIMIT        # a new day shows a full count
    bare = {k: v for k, v in state.items() if k != 'swans'}
    assert swans.public(bare, T0)['left'] == swans.DAILY_LIMIT


@pytest.mark.parametrize('bad', [[], {'day': 1}, dict(day=1, fed=swans.DAILY_LIMIT + 1, next_at=0, total=0),
                                 dict(day=1, fed=-1, next_at=0, total=0), dict(day=1, fed=0, next_at=0, total=True)])
def test_bad_state_is_rejected(bad):
    state = swan_farm()
    state['swans'] = bad
    with pytest.raises(FarmError):
        validate_state(state)


def test_neighbours_never_see_swan_state():
    state, visitor = swan_farm(), swan_farm()
    visitor['id'] = str(uuid4())
    state['settings']['visibility'] = 'public'
    feed(state)
    assert project(state, state, T0)['swans']['left'] == swans.DAILY_LIMIT - 1
    assert 'swans' not in project(state, visitor, T0)


def test_postgres_replay_charges_once_and_neighbour_view_is_clean(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as owner, player(env, 'telegram') as other:
            async with env.db.transaction() as db:
                unit = Unit(db, env.schema)
                state = await unit.by_account(owner.account_id)
                state['xp'] = LEVELS[FISHING_LEVEL - 1]
                state['inventory']['wheat'] = 10
                state['settings']['visibility'] = 'public'
                validate_state(state)
                await unit.save(state)
            before = await raw_farm(env, owner)
            key = str(uuid4())
            first = await accepted(owner, 'feed_swans', {}, key=key)
            replay = await accepted(owner, 'feed_swans', {}, key=key)
            assert first == replay
            after = await raw_farm(env, owner)
            assert after['inventory']['wheat'] == before['inventory']['wheat'] - swans.COST
            assert after['xp'] > before['xp'] and after['swans']['fed'] == 1
            assert (await view(owner))['swans']['left'] == swans.DAILY_LIMIT - 1
            wait = await command(owner, 'feed_swans', {})
            assert wait.status_code == 409
            assert 'swans' not in await view(other, owner.farm_id)
            foreign = await command(other, 'feed_swans', {}, target=owner.farm_id)
            assert foreign.status_code == 403
            env.now[0] += swans.COOLDOWN
            await accepted(owner, 'feed_swans', {})
            assert (await raw_farm(env, owner))['swans']['total'] == 2
    asyncio.run(scenario())


def test_projection_names_its_moscow_day_so_the_client_can_roll_over_midnight():
    state = swan_farm()
    state['swans'] = dict(day=moscow_day(T0), fed=swans.DAILY_LIMIT, next_at=0, total=swans.DAILY_LIMIT)
    view = swans.public(state, T0)
    assert view['left'] == 0 and view['day'] == moscow_day(T0)
    midnight = (moscow_day(T0) + 1) * DAY - 3 * 3600                          # next Moscow midnight
    nxt = swans.public(state, midnight + 5)
    assert nxt['day'] == moscow_day(T0) + 1 and nxt['left'] == swans.DAILY_LIMIT
