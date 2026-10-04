import pytest

from domain.mafia import (cast_vote, join_lobby, night_action, own_role, open_voting,
                          phase_due, public_lobby, resolve_night, resolve_vote,
                          restart_lobby, set_ready, start_lobby)


def test_ready_lobby_assigns_one_private_role_per_player():
    lobby = None
    for user_id in range(1, 5):
        lobby, changed = join_lobby(lobby, chat_id=-100, user_id=user_id, name=f'Player {user_id}')
        assert changed
    for user_id in range(1, 5):
        lobby = set_ready(lobby, chat_id=-100, user_id=user_id, ready=True,
                          expected_revision=lobby['revision'])
    lobby = start_lobby(lobby, chat_id=-100, user_id=1, expected_revision=lobby['revision'])
    assert lobby['status'] == 'night'
    assert set(lobby['assignments']) == {'1', '2', '3', '4'}
    assert sorted(lobby['assignments'].values()) == ['citizen', 'citizen', 'citizen', 'mafia']
    assert public_lobby(lobby, chat_id=-100, viewer_id=1)['status'] == 'night'
    assert 'assignments' not in public_lobby(lobby, chat_id=-100, viewer_id=1)
    assert own_role(lobby, chat_id=-100, user_id=2)['role'] in {'mafia', 'citizen'}
    with pytest.raises(PermissionError):
        own_role(lobby, chat_id=-100, user_id=99)


def test_only_host_can_start_and_all_players_must_be_ready():
    lobby = None
    for user_id in range(1, 5):
        lobby, _ = join_lobby(lobby, chat_id=-200, user_id=user_id, name=str(user_id))
    with pytest.raises(PermissionError):
        start_lobby(lobby, chat_id=-200, user_id=2, expected_revision=lobby['revision'])
    with pytest.raises(ValueError):
        start_lobby(lobby, chat_id=-200, user_id=1, expected_revision=lobby['revision'])


def test_full_night_day_vote_cycle_keeps_secrets_private(monkeypatch):
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)
    lobby = None
    for user_id in range(1, 8):
        lobby, _ = join_lobby(lobby, chat_id=-300, user_id=user_id, name=f'Player {user_id}')
    for user_id in range(1, 8):
        lobby = set_ready(lobby, chat_id=-300, user_id=user_id, ready=True,
                          expected_revision=lobby['revision'])
    lobby = start_lobby(lobby, chat_id=-300, user_id=1, expected_revision=lobby['revision'])
    assert lobby['assignments'] == {'1': 'mafia', '2': 'mafia', '3': 'citizen',
        '4': 'citizen', '5': 'citizen', '6': 'detective', '7': 'doctor'}
    for actor, seat in [(1, 'p3'), (2, 'p3'), (6, 'p1'), (7, 'p4')]:
        lobby = night_action(lobby, chat_id=-300, user_id=actor, target_seat=seat,
                             expected_revision=lobby['revision'])
    lobby = resolve_night(lobby, chat_id=-300, user_id=1, expected_revision=lobby['revision'])
    public = public_lobby(lobby, chat_id=-300, viewer_id=4)
    assert lobby['status'] == 'day' and 3 not in lobby['alive']
    assert 'assignments' not in public and 'user_id' not in str(public)
    assert own_role(lobby, chat_id=-300, user_id=6)['investigation']['is_mafia'] is True
    lobby = open_voting(lobby, chat_id=-300, user_id=1, expected_revision=lobby['revision'])
    for actor, seat in [(1, 'p4'), (2, 'p4'), (4, 'p1'), (5, 'p1'), (6, 'p1'), (7, 'p1')]:
        lobby = cast_vote(lobby, chat_id=-300, user_id=actor, target_seat=seat,
                          expected_revision=lobby['revision'])
    lobby = resolve_vote(lobby, chat_id=-300, user_id=1, expected_revision=lobby['revision'])
    assert lobby['status'] == 'night' and lobby['round'] == 2 and 1 not in lobby['alive']
    for actor, seat in [(2, 'p4'), (6, 'p2'), (7, 'p5')]:
        lobby = night_action(lobby, chat_id=-300, user_id=actor, target_seat=seat,
                             expected_revision=lobby['revision'])
    lobby = resolve_night(lobby, chat_id=-300, user_id=1, expected_revision=lobby['revision'])
    lobby = open_voting(lobby, chat_id=-300, user_id=1, expected_revision=lobby['revision'])
    for actor in (2, 5, 6, 7):
        target = 'p5' if actor == 2 else 'p2'
        lobby = cast_vote(lobby, chat_id=-300, user_id=actor, target_seat=target,
                          expected_revision=lobby['revision'])
    lobby = resolve_vote(lobby, chat_id=-300, user_id=1, expected_revision=lobby['revision'])
    assert lobby['status'] == 'finished' and lobby['winner'] == 'citizens'
    lobby = restart_lobby(lobby, chat_id=-300, user_id=1,
                          expected_revision=lobby['revision'])
    assert lobby['status'] == 'lobby' and all(not player['ready'] for player in lobby['players'])
    assert 'assignments' not in lobby and 'winner' not in lobby


def test_dead_players_and_stale_actions_are_rejected(monkeypatch):
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)
    lobby = None
    for uid in range(1, 5):
        lobby, _ = join_lobby(lobby, chat_id=-400, user_id=uid, name=str(uid))
        lobby = set_ready(lobby, chat_id=-400, user_id=uid, ready=True,
                          expected_revision=lobby['revision'])
    lobby = start_lobby(lobby, chat_id=-400, user_id=1, expected_revision=lobby['revision'])
    revision = lobby['revision']
    lobby = night_action(lobby, chat_id=-400, user_id=1, target_seat='p2', expected_revision=revision)
    with pytest.raises(RuntimeError):
        night_action(lobby, chat_id=-400, user_id=1, target_seat='p3', expected_revision=revision)
    with pytest.raises(PermissionError):
        night_action(lobby, chat_id=-400, user_id=2, target_seat='p1', expected_revision=lobby['revision'])


def test_expired_phases_advance_without_missing_actions_or_votes(monkeypatch):
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)
    lobby = None
    for uid in range(1, 5):
        lobby, _ = join_lobby(lobby, chat_id=-500, user_id=uid, name=str(uid))
        lobby = set_ready(lobby, chat_id=-500, user_id=uid, ready=True,
                          expected_revision=lobby['revision'])
    lobby = start_lobby(
        lobby, chat_id=-500, user_id=1, expected_revision=lobby['revision'], now=1_000
    )
    assert lobby['phase_deadline'] == 1_090
    assert not phase_due(lobby, now=1_089) and phase_due(lobby, now=1_090)
    with pytest.raises(ValueError, match='завершилась'):
        night_action(lobby, chat_id=-500, user_id=1, target_seat='p2',
                     expected_revision=lobby['revision'], now=1_090)
    lobby = resolve_night(
        lobby, chat_id=-500, user_id=1, expected_revision=lobby['revision'],
        allow_incomplete=True, now=1_090,
    )
    assert lobby['status'] == 'day' and lobby['phase_deadline'] == 1_270
    lobby = open_voting(
        lobby, chat_id=-500, user_id=1, expected_revision=lobby['revision'], now=1_270
    )
    assert lobby['phase_deadline'] == 1_360
    lobby = resolve_vote(
        lobby, chat_id=-500, user_id=1, expected_revision=lobby['revision'],
        allow_incomplete=True, now=1_360,
    )
    assert lobby['status'] == 'night' and lobby['round'] == 2
    assert lobby['phase_deadline'] == 1_450
