import pytest

from domain.mafia import (cast_vote, join_lobby, night_action, own_role, open_voting,
                          normalize_discussion_message, phase_due, public_lobby, resolve_night, resolve_vote,
                          restart_lobby, set_ready, start_lobby)
from uuid import UUID


def _account(user_id):
    return str(UUID(int=user_id))


def test_ready_lobby_assigns_one_private_role_per_player():
    lobby = None
    for user_id in range(1, 5):
        lobby, changed = join_lobby(lobby, chat_id=-100, account_id=_account(user_id), name=f'Player {user_id}')
        assert changed
    for user_id in range(1, 5):
        lobby = set_ready(lobby, chat_id=-100, account_id=_account(user_id), ready=True,
                          expected_revision=lobby['revision'])
    lobby = start_lobby(lobby, chat_id=-100, account_id=_account(1), expected_revision=lobby['revision'])
    assert lobby['status'] == 'night'
    assert set(lobby['assignments']) == {_account(i) for i in range(1, 5)}
    assert sorted(lobby['assignments'].values()) == ['citizen', 'citizen', 'citizen', 'mafia']
    assert public_lobby(lobby, chat_id=-100, viewer_account_id=_account(1))['status'] == 'night'
    assert 'assignments' not in public_lobby(lobby, chat_id=-100, viewer_account_id=_account(1))
    assert own_role(lobby, chat_id=-100, account_id=_account(2))['role'] in {'mafia', 'citizen'}
    with pytest.raises(PermissionError):
        own_role(lobby, chat_id=-100, account_id=_account(99))


def test_mafia_discussion_message_validation_preserves_plain_text():
    assert normalize_discussion_message('  <не html>\nобычный текст  ') == '<не html>\nобычный текст'
    with pytest.raises(ValueError, match='Пустое'):
        normalize_discussion_message(' \n ')
    with pytest.raises(ValueError, match='1000'):
        normalize_discussion_message('x' * 1001)
    with pytest.raises(ValueError, match='управляющие'):
        normalize_discussion_message('опасно\x00')


def test_only_host_can_start_and_all_players_must_be_ready():
    lobby = None
    for user_id in range(1, 5):
        lobby, _ = join_lobby(lobby, chat_id=-200, account_id=_account(user_id), name=str(user_id))
    with pytest.raises(PermissionError):
        start_lobby(lobby, chat_id=-200, account_id=_account(2), expected_revision=lobby['revision'])
    with pytest.raises(ValueError):
        start_lobby(lobby, chat_id=-200, account_id=_account(1), expected_revision=lobby['revision'])


def test_full_night_day_vote_cycle_keeps_secrets_private(monkeypatch):
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)
    lobby = None
    for user_id in range(1, 8):
        lobby, _ = join_lobby(lobby, chat_id=-300, account_id=_account(user_id), name=f'Player {user_id}')
    for user_id in range(1, 8):
        lobby = set_ready(lobby, chat_id=-300, account_id=_account(user_id), ready=True,
                          expected_revision=lobby['revision'])
    lobby = start_lobby(lobby, chat_id=-300, account_id=_account(1), expected_revision=lobby['revision'])
    assert list(lobby['assignments'].values()) == ['mafia', 'mafia', 'citizen',
        'citizen', 'citizen', 'detective', 'doctor']
    night_phase = lobby['phase_revision']
    for actor, seat in [(1, 'p3'), (2, 'p3'), (6, 'p1'), (7, 'p4')]:
        lobby = night_action(lobby, chat_id=-300, account_id=_account(actor), target_seat=seat,
                             expected_revision=night_phase)
    lobby = resolve_night(lobby, chat_id=-300, account_id=_account(1), expected_revision=lobby['revision'])
    public = public_lobby(lobby, chat_id=-300, viewer_account_id=_account(4))
    assert lobby['status'] == 'day' and _account(3) not in lobby['alive']
    assert 'assignments' not in public and 'user_id' not in str(public)
    assert own_role(lobby, chat_id=-300, account_id=_account(6))['investigation']['is_mafia'] is True
    lobby = open_voting(lobby, chat_id=-300, account_id=_account(1), expected_revision=lobby['revision'])
    voting_phase = lobby['phase_revision']
    lobby = cast_vote(lobby, chat_id=-300, account_id=_account(1), target_seat='p4',
                      expected_revision=voting_phase)
    with pytest.raises(ValueError, match='уже проголосовали'):
        cast_vote(lobby, chat_id=-300, account_id=_account(1), target_seat='p2',
                  expected_revision=voting_phase)
    for actor, seat in [(2, 'p4'), (4, 'p1'), (5, 'p1'), (6, 'p1'), (7, 'p1')]:
        lobby = cast_vote(lobby, chat_id=-300, account_id=_account(actor), target_seat=seat,
                          expected_revision=voting_phase)
    lobby = resolve_vote(lobby, chat_id=-300, account_id=_account(1), expected_revision=lobby['revision'])
    assert lobby['status'] == 'night' and lobby['round'] == 2 and _account(1) not in lobby['alive']
    night_phase = lobby['phase_revision']
    for actor, seat in [(2, 'p4'), (6, 'p2'), (7, 'p5')]:
        lobby = night_action(lobby, chat_id=-300, account_id=_account(actor), target_seat=seat,
                             expected_revision=night_phase)
    lobby = resolve_night(lobby, chat_id=-300, account_id=_account(1), expected_revision=lobby['revision'])
    lobby = open_voting(lobby, chat_id=-300, account_id=_account(1), expected_revision=lobby['revision'])
    voting_phase = lobby['phase_revision']
    for actor in (2, 5, 6, 7):
        target = 'p5' if actor == 2 else 'p2'
        lobby = cast_vote(lobby, chat_id=-300, account_id=_account(actor), target_seat=target,
                          expected_revision=voting_phase)
    lobby = resolve_vote(lobby, chat_id=-300, account_id=_account(1), expected_revision=lobby['revision'])
    assert lobby['status'] == 'finished' and lobby['winner'] == 'citizens'
    lobby = restart_lobby(lobby, chat_id=-300, account_id=_account(1),
                          expected_revision=lobby['revision'])
    assert lobby['status'] == 'lobby' and all(not player['ready'] for player in lobby['players'])
    assert 'assignments' not in lobby and 'winner' not in lobby


def test_dead_players_and_stale_actions_are_rejected(monkeypatch):
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)
    lobby = None
    for uid in range(1, 5):
        lobby, _ = join_lobby(lobby, chat_id=-400, account_id=_account(uid), name=str(uid))
        lobby = set_ready(lobby, chat_id=-400, account_id=_account(uid), ready=True,
                          expected_revision=lobby['revision'])
    lobby = start_lobby(lobby, chat_id=-400, account_id=_account(1), expected_revision=lobby['revision'])
    revision = lobby['phase_revision']
    lobby = night_action(lobby, chat_id=-400, account_id=_account(1), target_seat='p2', expected_revision=revision)
    with pytest.raises(RuntimeError):
        night_action(lobby, chat_id=-400, account_id=_account(1), target_seat='p3', expected_revision=revision + 1)
    with pytest.raises(ValueError, match='уже сделали'):
        night_action(lobby, chat_id=-400, account_id=_account(1), target_seat='p3', expected_revision=revision)
    with pytest.raises(PermissionError):
        night_action(lobby, chat_id=-400, account_id=_account(2), target_seat='p1', expected_revision=revision)


def test_expired_phases_advance_without_missing_actions_or_votes(monkeypatch):
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)
    lobby = None
    for uid in range(1, 5):
        lobby, _ = join_lobby(lobby, chat_id=-500, account_id=_account(uid), name=str(uid))
        lobby = set_ready(lobby, chat_id=-500, account_id=_account(uid), ready=True,
                          expected_revision=lobby['revision'])
    lobby = start_lobby(
        lobby, chat_id=-500, account_id=_account(1), expected_revision=lobby['revision'], now=1_000
    )
    assert lobby['phase_deadline'] == 1_090
    assert not phase_due(lobby, now=1_089) and phase_due(lobby, now=1_090)
    with pytest.raises(ValueError, match='завершилась'):
        night_action(lobby, chat_id=-500, account_id=_account(1), target_seat='p2',
                     expected_revision=lobby['phase_revision'], now=1_090)
    lobby = resolve_night(
        lobby, chat_id=-500, account_id=_account(1), expected_revision=lobby['revision'],
        allow_incomplete=True, now=1_090,
    )
    assert lobby['status'] == 'day' and lobby['phase_deadline'] == 1_270
    lobby = open_voting(
        lobby, chat_id=-500, account_id=_account(1), expected_revision=lobby['revision'], now=1_270
    )
    assert lobby['phase_deadline'] == 1_360
    lobby = resolve_vote(
        lobby, chat_id=-500, account_id=_account(1), expected_revision=lobby['revision'],
        allow_incomplete=True, now=1_360,
    )
    assert lobby['status'] == 'night' and lobby['round'] == 2
    assert lobby['phase_deadline'] == 1_450


def test_standalone_account_lobby_uses_the_same_rules_without_telegram_ids(monkeypatch):
    from uuid import uuid4

    ids = [str(uuid4()) for _ in range(4)]
    room_id = str(uuid4())
    lobby = None
    for account_id in ids:
        lobby, changed = join_lobby(
            lobby, room_id=room_id, account_id=account_id, name='Guest',
        )
        assert changed
    assert lobby['state_version'] == 2 and lobby['room_id'] == room_id
    assert 'scope' not in lobby
    assert 'chat_id' not in lobby and 'host_id' not in lobby
    for account_id in ids:
        lobby = set_ready(
            lobby, room_id=room_id, account_id=account_id, ready=True,
            expected_revision=lobby['revision'],
        )
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)
    lobby = start_lobby(
        lobby, room_id=room_id, account_id=ids[0], expected_revision=lobby['revision'], now=1000,
    )
    assert set(lobby['assignments']) == set(ids)
    public = public_lobby(lobby, room_id=room_id, viewer_account_id=ids[0])
    assert public['is_host'] and public['joined'] and public['status'] == 'night'
    assert 'assignments' not in public and all(account_id not in str(public) for account_id in ids)
    role = own_role(lobby, room_id=room_id, account_id=ids[0])
    assert role['role'] == 'mafia' and role['alive']

    phase_revision = lobby['phase_revision']
    for account_id in ids:
        actor_role = lobby['assignments'][account_id]
        if actor_role == 'citizen':
            continue
        targets = [other for other in ids if other != account_id]
        if actor_role == 'mafia':
            targets = [other for other in targets if lobby['assignments'][other] != 'mafia']
        target = targets[0]
        seat = f"p{ids.index(target) + 1}"
        lobby = night_action(
            lobby, room_id=room_id, account_id=account_id, target_seat=seat,
            expected_revision=phase_revision, now=1001,
        )
    lobby = resolve_night(
        lobby, room_id=room_id, account_id=ids[0], expected_revision=lobby['revision'],
        now=1090,
    )
    assert lobby['status'] in {'day', 'finished'}
    assert lobby['phase_deadline'] is None or lobby['phase_deadline'] > 1090
