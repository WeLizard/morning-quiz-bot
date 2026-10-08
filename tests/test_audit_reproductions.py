"""Small, isolated reproducers for findings in the 2026-10-08 audit.

These isolated tests preserve the audit reproductions and assert the corrected
contract once an issue is fixed. PostgreSQL acceptance remains separate.
"""

from types import SimpleNamespace

import pytest

from domain.mafia import join_lobby, night_action, set_ready, start_lobby
from uuid import UUID
from storage.games import GameRepository


def test_aud007_independent_mafia_actions_use_a_phase_revision(monkeypatch):
    """Independent role actions in one phase remain valid after another actor acts."""
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda _self, values: None)
    lobby = None
    for user_id in range(1, 8):
        lobby, _ = join_lobby(lobby, chat_id=-300, account_id=str(UUID(int=user_id)), name=str(user_id))
    for user_id in range(1, 8):
        lobby = set_ready(lobby, chat_id=-300, account_id=str(UUID(int=user_id)), ready=True,
                          expected_revision=lobby['revision'])
    lobby = start_lobby(lobby, chat_id=-300, account_id=str(UUID(int=1)),
                        expected_revision=lobby['revision'])
    # Deterministic role assignment in this domain helper: players 1 and 2 are mafia.
    phase_revision = lobby['phase_revision']
    lobby = night_action(lobby, chat_id=-300, account_id=str(UUID(int=1)), target_seat='p3',
                         expected_revision=phase_revision)
    with pytest.raises(ValueError, match='уже сделали'):
        night_action(lobby, chat_id=-300, account_id=str(UUID(int=1)), target_seat='p4',
                     expected_revision=phase_revision)
    lobby = night_action(lobby, chat_id=-300, account_id=str(UUID(int=2)), target_seat='p4',
                         expected_revision=phase_revision)
    assert lobby['phase_revision'] == phase_revision
    assert lobby['revision'] > phase_revision
    assert lobby['night_actions']['mafia'] == {
        str(UUID(int=1)): str(UUID(int=3)),
        str(UUID(int=2)): str(UUID(int=4)),
    }


class _ExistingCommandSession:
    def __init__(self, existing):
        self.existing = existing
        self.scalar_calls = 0

    async def scalar(self, _statement):
        self.scalar_calls += 1
        # PostgreSQL INSERT ... ON CONFLICT DO NOTHING returns no inserted ID,
        # then the repository loads the previously committed receipt.
        return None if self.scalar_calls == 1 else self.existing


def test_aud008_command_id_replay_is_rejected_for_a_different_game(monkeypatch):
    from uuid import UUID

    account_id = UUID('4dd8adbe-9626-4765-92c7-34dbf8111511')
    receipt = SimpleNamespace(
        id='same-command-id', game_id='game-A', actor_user_id=7,
        actor_account_id=account_id,
        kind='mafia.vote', expected_revision=3, payload={'target_seat': 'p2'},
        status='completed', result={'cached_from': 'game-A'},
    )
    repository = GameRepository(_ExistingCommandSession(receipt))

    async def account_for_user(_user_id):
        return account_id

    monkeypatch.setattr(repository, 'account_for_telegram_user', account_for_user)

    with pytest.raises(RuntimeError, match='другой команды или игры'):
        __import__('asyncio').run(repository.reserve_command(
            command_id=receipt.id, game_id='game-B', actor_user_id=7,
            kind='mafia.vote', expected_revision=3, payload={'target_seat': 'p2'},
        ))
