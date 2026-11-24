"""Farm grant validation, ownership, transaction and claim idempotency."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from qw_farm import farm_rewards
from qw_farm.domain import FarmError, apply, new_farm, project, validate_state


NOW = 1_800_000_000
GIFT = 'farm-prize-1'
TITLE = 'Приз для фермы'
CONTENTS = dict(title=TITLE, message='За участие.', coins=30, items={'wheat': 2}, decor=['fd_cup'])


def farm():
    return new_farm(str(uuid4()), 'Фермер', NOW)


def fail(code, action, *args, **kwargs):
    with pytest.raises(FarmError) as raised:
        action(*args, **kwargs)
    assert raised.value.code == code


def run(state, kind, data, command_id='award-command'):
    return apply(state, state, kind, data, NOW, command_id)


@pytest.mark.parametrize('invalid', [
    {'title': ''}, {'title': 'а' * 81}, {'message': 'а' * 501}, {'message': 'строка\nстрока'},
    {'coins': True}, {'coins': 10**12 + 1}, {'items': {'no-such-item': 1}}, {'items': {'wheat': -1}},
    {'items': {'dye_indigo': 1}}, {'decor': ['road']}, {'decor': ['mill']}, {'decor': ['fd_cup', 'fd_cup']},
    {'coins': 0, 'items': {}, 'decor': []},
])
def test_enqueues_only_valid_reward_contents(invalid):
    state = farm()
    before = deepcopy(state)
    fail('invalid_farm_reward', farm_rewards.enqueue, state, GIFT, NOW, **(CONTENTS | invalid))
    assert state == before


def test_claim_is_atomic_and_private_and_decor_uses_one_free_placement():
    state, visitor = farm(), farm()
    state['settings']['visibility'] = 'public'
    assert project(state, state, NOW)['farm_rewards'] == []
    assert farm_rewards.enqueue(state, GIFT, NOW, **CONTENTS)
    assert not farm_rewards.enqueue(state, GIFT, NOW + 5, **CONTENTS)
    fail('farm_reward_key_reused', farm_rewards.enqueue, state, GIFT, NOW, **(CONTENTS | {'coins': 31}))
    projection = project(state, state, NOW)
    assert projection['farm_rewards'] == [dict(id=GIFT, created_at=NOW, **CONTENTS)]
    assert projection['farm_reward_decor'] == {}
    guest = project(state, visitor, NOW)
    assert 'farm_rewards' not in guest and 'farm_reward_decor' not in guest
    data = {'reward': GIFT}
    fail('not_owner', apply, visitor, state, 'claim_farm_reward', data, NOW, 'foreign-award')
    fail('invalid_command', run, state, 'claim_farm_reward', data | {'coins': 1})
    fail('unknown_command', run, state, 'enqueue_farm_reward', data)

    valid_claim = deepcopy(state)
    state['coins'] = 10**12 - 29
    before = deepcopy(state)
    fail('balance_full', farm_rewards.claim, state, GIFT, NOW)
    assert state == before
    state = valid_claim
    state['inventory']['wheat'] = 10**9 - 1
    before = deepcopy(state)
    fail('inventory_full', farm_rewards.claim, state, GIFT, NOW)
    assert state == before
    state['inventory']['wheat'] = 2
    initial_coins = state['coins']

    run(state, 'claim_farm_reward', data)
    assert state['inventory']['wheat'] == 4 and state['coins'] == initial_coins + 30
    projected = project(state, state, NOW)
    assert projected['farm_rewards'] == [] and projected['farm_reward_decor'] == {'fd_cup': 1}
    fail('farm_reward_claimed', run, state, 'claim_farm_reward', data)
    fail('occupied', run, state, 'build', dict(type='fd_cup', x=0, y=0))
    assert farm_rewards.decor_credits(state) == {'fd_cup': 1}
    run(state, 'build', dict(type='fd_cup', x=6, y=6))
    assert state['objects'][-1]['paid'] == 0 and state['coins'] == initial_coins + 30
    assert farm_rewards.decor_credits(state) == {}
    fail('farm_reward_decor_unavailable', run, state, 'build', dict(type='fd_cup', x=7, y=7, gift=True))
    fail('locked', run, state, 'build', dict(type='fd_cup', x=7, y=7))
    assert not farm_rewards.enqueue(state, GIFT, NOW + 30, **CONTENTS)
    validate_state(json.loads(json.dumps(state)))


def test_merge_deduplicates_pending_and_preserves_claimed_and_spent_decor():
    main, secondary = farm(), farm()
    farm_rewards.enqueue(main, GIFT, NOW, **CONTENTS)
    farm_rewards.enqueue(secondary, GIFT, NOW + 1, **CONTENTS)
    other_id = 'separate-award'
    farm_rewards.enqueue(secondary, other_id, NOW + 2, **CONTENTS)
    farm_rewards.claim(secondary, GIFT, NOW + 3)
    farm_rewards.take_decor(secondary, 'fd_cup')
    before = deepcopy(secondary)
    farm_rewards.merge(main, secondary)
    assert secondary == before
    assert [r['id'] for r in farm_rewards.pending(main)] == [other_id]
    assert farm_rewards.decor_credits(main) == {}
    assert main['farm_rewards'][GIFT]['created_at'] == NOW
    fail('farm_reward_claimed', farm_rewards.claim, main, GIFT, NOW + 4)
    farm_rewards.claim(main, other_id, NOW + 4)
    assert farm_rewards.decor_credits(main) == {'fd_cup': 1}
    validate_state(main)
