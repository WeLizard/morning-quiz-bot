"""Pure persisted identity compatibility tests; no database or gameplay rules."""

from copy import deepcopy
from uuid import UUID

import pytest

from domain.mafia_state import canonicalize_mafia_state, restore_legacy_mafia_state


A = '00000000-0000-4000-8000-000000000001'
B = '00000000-0000-4000-8000-000000000002'
ROOM = '00000000-0000-4000-8000-000000000003'
CHAT = -100123
TG_ROOM = f'telegram:{CHAT}'
MAPPING = {11: UUID(A), '22': B}


def legacy_telegram():
    return {
        'mode': 'mafia_lobby', 'chat_id': CHAT, 'host_id': 11,
        'status': 'interrupted', 'revision': 91, 'phase_revision': 37,
        'players': [{'user_id': 22, 'name': 'Two', 'ready': 'unchanged', 'extra': {'x': [1, 2]}},
                    {'user_id': 11, 'name': 'One', 'ready': False}],
        'assignments': {'22': 'future-role', '11': 'mafia'},
        'alive': [22, 11],
        'night_actions': {'detective': {'22': 11}, 'future-role': {'11': 22}},
        'votes': {'22': 11, '11': 22},
        'investigations': {'22': [{'target': 11, 'round': 8, 'is_mafia': True, 'future': ['untouched']} ]},
        'phase_deadline': 1780000000.5, 'started_at': '2026-10-08T01:02:03Z',
        'history': [{'type': 'night_result', 'eliminated': 'p1', 'round': 7, 'unknown': {'user_id': 'historical text'}}],
        'unknown': {'opaque': [{'account_id': 'not an identity position'}]},
    }


def test_telegram_upgrade_preserves_interrupted_state_and_all_non_identity_data():
    old = legacy_telegram()
    original = deepcopy(old)
    state = canonicalize_mafia_state(old, TG_ROOM, MAPPING, CHAT)
    assert state['state_version'] == 2
    assert state['room_id'] == TG_ROOM and state['host_account_id'] == A
    assert [p['account_id'] for p in state['players']] == [B, A]
    assert state['assignments'] == {B: 'future-role', A: 'mafia'}
    assert state['alive'] == [B, A]
    assert state['night_actions'] == {'detective': {B: A}, 'future-role': {A: B}}
    assert state['votes'] == {B: A, A: B}
    assert state['investigations'][B][0] == {**old['investigations']['22'][0], 'target': A}
    assert not {'scope', 'chat_id', 'host_id'} & state.keys()
    assert all('user_id' not in p for p in state['players'])
    for key in ('status', 'revision', 'phase_revision', 'phase_deadline', 'started_at', 'history', 'unknown'):
        assert state[key] == old[key]
    assert state['players'][0]['ready'] == 'unchanged'
    assert list(state['assignments']) == [B, A]
    assert old == original
    assert restore_legacy_mafia_state(state, 'telegram', CHAT, {A: 11, B: 22}) == old
    assert state == canonicalize_mafia_state(old, TG_ROOM, MAPPING)


def test_standalone_round_trip_and_v2_idempotence_do_not_normalize_rules():
    state = canonicalize_mafia_state(legacy_telegram(), TG_ROOM, MAPPING)
    state['room_id'] = ROOM
    old = deepcopy(state)
    old.pop('state_version')
    old['scope'] = 'standalone'
    result = canonicalize_mafia_state(old, ROOM)
    assert result == state
    assert canonicalize_mafia_state(result, ROOM) == result
    assert restore_legacy_mafia_state(result, 'standalone') == old
    result['players'][0]['extra']['x'].append(3)
    assert old['players'][0]['extra']['x'] == [1, 2]


@pytest.mark.parametrize('mapping', [None, {}, {11: A}, {11: A, 22: A}, {11: A, '11': B, 22: B}, {11: 'bad', 22: B}, {True: A, 22: B}])
def test_missing_duplicate_conflicting_or_malformed_mapping_fails(mapping):
    with pytest.raises(ValueError):
        canonicalize_mafia_state(legacy_telegram(), TG_ROOM, mapping)


@pytest.mark.parametrize('field,value', [
    ('players', []), ('players', [{'user_id': 11}, {'user_id': 11}]),
    ('host_id', 33), ('assignments', None), ('assignments', {11: 'mafia'}),
    ('assignments', {'33': 'mafia'}), ('alive', [11, 11]), ('alive', ['11']),
    ('night_actions', {'mafia': []}), ('night_actions', {'mafia': {'11': 33}}),
    ('votes', {'11': None}), ('investigations', {'11': {}}),
    ('investigations', {'11': [{'round': 1}]}), ('investigations', {'11': [{'target': 33}]}),
    ('state_version', 3), ('state_version', True), ('scope', 'unknown'), ('scope', []),
    ('host_account_id', B), ('room_id', ROOM), ('chat_id', -123),
])
def test_malformed_legacy_identity_positions_fail_without_mutating_input(field, value):
    old = legacy_telegram()
    old[field] = value
    original = deepcopy(old)
    with pytest.raises(ValueError):
        canonicalize_mafia_state(old, TG_ROOM, MAPPING, CHAT)
    assert old == original


@pytest.mark.parametrize('mutate', [
    lambda s: s.update(chat_id=CHAT), lambda s: s.update(scope='standalone'),
    lambda s: s.update(host_id=11), lambda s: s['players'][0].update(user_id=22),
    lambda s: s['players'][0].update(account_id='bad'),
    lambda s: s['players'][1].update(account_id=B),
    lambda s: s.update(room_id=ROOM), lambda s: s.update(host_account_id=ROOM),
])
def test_canonical_state_is_validated_not_blindly_accepted(mutate):
    state = canonicalize_mafia_state(legacy_telegram(), TG_ROOM, MAPPING)
    mutate(state)
    with pytest.raises(ValueError):
        canonicalize_mafia_state(state, TG_ROOM)


def test_downgrade_rejects_missing_or_ambiguous_mapping_and_wrong_room():
    state = canonicalize_mafia_state(legacy_telegram(), TG_ROOM, MAPPING)
    original = deepcopy(state)
    for mapping in (None, {A: 11}, {A: 11, B: 11}, {A: True, B: 22}):
        with pytest.raises(ValueError):
            restore_legacy_mafia_state(state, 'telegram', CHAT, mapping)
    with pytest.raises(ValueError):
        restore_legacy_mafia_state(state, 'telegram', -123, {A: 11, B: 22})
    with pytest.raises(ValueError):
        restore_legacy_mafia_state(state, 'standalone')
    with pytest.raises(ValueError):
        restore_legacy_mafia_state(state, 'unknown')
    assert state == original


def test_legacy_player_embedded_account_must_match_mapping():
    old = legacy_telegram()
    old['players'][0]['account_id'] = A
    with pytest.raises(ValueError):
        canonicalize_mafia_state(old, TG_ROOM, MAPPING)


def test_even_optional_mapping_on_v2_must_not_be_ambiguous():
    state = canonicalize_mafia_state(legacy_telegram(), TG_ROOM, MAPPING)
    with pytest.raises(ValueError):
        canonicalize_mafia_state(state, TG_ROOM, {11: A, 22: A})


@pytest.mark.parametrize('room,chat', [(ROOM, CHAT), ('telegram:0', None), ('bad', None), (TG_ROOM, -999)])
def test_invalid_room_and_chat_binding_fails(room, chat):
    with pytest.raises(ValueError):
        canonicalize_mafia_state(legacy_telegram(), room, MAPPING, chat)
