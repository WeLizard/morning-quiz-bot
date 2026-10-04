"""Application commands and projections for the shared Mafia lobby.

This module deliberately knows nothing about Telegram, HTTP or the Mini App UI.
Adapters pass an actor and render the returned projection in their own format.
"""

from storage.admin_actions import operation_fence, require_access
from domain.mafia import (
    cast_vote,
    join_lobby,
    night_action,
    open_voting,
    own_role,
    phase_due,
    public_lobby,
    resolve_night,
    resolve_vote,
    restart_lobby,
    set_ready,
    start_lobby,
)
from storage.games import GameRepository
from storage.models import ChatMember
from storage.notifications import NotificationQueue


class MafiaApplicationService:
    """Run Mafia use cases inside an existing database transaction."""

    def __init__(self, session):
        self.session = session
        self.games = GameRepository(session)

    async def _read(self, chat_id: int):
        return await self.games.current(chat_id=chat_id, mode='mafia')

    async def _lock(self, chat_id: int, actor_user_id: int | None = None):
        # All game writes take the same shared operational fence as scores and
        # sessions, so an exclusive reset cannot race a Mafia transition.
        await operation_fence(self.session)
        await require_access(self.session, chat_id, actor_user_id)
        if actor_user_id is not None and await self.session.get(
            ChatMember, (chat_id, actor_user_id)
        ) is None:
            raise PermissionError('Игрок больше не состоит в этом чате.')
        return await self.games.current(chat_id=chat_id, mode='mafia', lock=True)

    async def lobby(self, *, chat_id: int, viewer_id: int) -> dict | None:
        row = await self._read(chat_id)
        return public_lobby(row.state if row else None, chat_id=chat_id, viewer_id=viewer_id)

    async def join(
        self, *, chat_id: int, user_id: int, name: str,
        command_id: str | None = None,
    ) -> dict:
        row = await self._lock(chat_id, user_id)
        lobby, changed = join_lobby(
            row.state if row else None, chat_id=chat_id, user_id=user_id, name=name
        )
        if row is None:
            row = await self.games.create_current(chat_id=chat_id, mode='mafia', state=lobby)
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_user_id=user_id,
            kind='mafia.join', expected_revision=None, payload={'name': name[:120]},
        )
        if cached:
            return result
        if changed and row.state != lobby:
            await self.games.sync_state(
                row, lobby, event_kind='player_joined', actor_user_id=user_id
            )
        result = {
            'lobby': public_lobby(lobby, chat_id=chat_id, viewer_id=user_id),
            'changed': changed,
        }
        await self.games.complete_command(command_id, result)
        return result

    async def ready(
        self,
        *,
        chat_id: int,
        user_id: int,
        ready: bool,
        expected_revision: int,
        command_id: str | None = None,
    ) -> dict:
        row = await self._lock(chat_id, user_id)
        if row is None:
            raise LookupError('Лобби ещё не создано.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_user_id=user_id,
            kind='mafia.ready', expected_revision=expected_revision,
            payload={'ready': ready},
        )
        if cached:
            return result
        lobby = set_ready(
            row.state if row else None,
            chat_id=chat_id,
            user_id=user_id,
            ready=ready,
            expected_revision=expected_revision,
        )
        await self.games.sync_state(row, lobby, event_kind='readiness_changed', actor_user_id=user_id)
        result = public_lobby(lobby, chat_id=chat_id, viewer_id=user_id)
        await self.games.complete_command(command_id, result)
        return result

    async def start(
        self, *, chat_id: int, user_id: int, expected_revision: int,
        command_id: str | None = None,
    ) -> dict:
        row = await self._lock(chat_id, user_id)
        if row is None:
            raise LookupError('Стол не найден.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_user_id=user_id,
            kind='mafia.start', expected_revision=expected_revision, payload={},
        )
        if cached:
            return result
        lobby = start_lobby(
            row.state if row else None,
            chat_id=chat_id,
            user_id=user_id,
            expected_revision=expected_revision,
        )
        await self.games.sync_state(row, lobby, event_kind='game_started', actor_user_id=user_id)
        result = public_lobby(lobby, chat_id=chat_id, viewer_id=user_id)
        await self.games.complete_command(command_id, result)
        return result

    async def restart(
        self, *, chat_id: int, user_id: int, expected_revision: int,
        command_id: str | None = None,
    ) -> dict:
        row = await self._lock(chat_id, user_id)
        if row is None:
            raise LookupError('Стол не найден.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_user_id=user_id,
            kind='mafia.restart', expected_revision=expected_revision, payload={},
        )
        if cached:
            return result
        lobby = restart_lobby(
            row.state if row else None,
            chat_id=chat_id,
            user_id=user_id,
            expected_revision=expected_revision,
        )
        await self.games.replace_current(row, state=lobby)
        result = public_lobby(lobby, chat_id=chat_id, viewer_id=user_id)
        await self.games.complete_command(command_id, result)
        return result

    async def role(self, *, chat_id: int, user_id: int) -> dict | None:
        row = await self._read(chat_id)
        return own_role(row.state if row else None, chat_id=chat_id, user_id=user_id)

    async def action(self, *, chat_id: int, user_id: int, target_seat: str,
                     expected_revision: int, command_id: str | None = None) -> dict:
        row = await self._lock(chat_id, user_id)
        if row is None:
            raise LookupError('Партия не найдена.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_user_id=user_id,
            kind='mafia.action', expected_revision=expected_revision,
            payload={'target_seat': target_seat},
        )
        if cached:
            return result
        game = night_action(row.state if row else None, chat_id=chat_id, user_id=user_id,
                            target_seat=target_seat, expected_revision=expected_revision)
        await self.games.sync_state(row, game, event_kind='night_action', actor_user_id=user_id)
        result = {'lobby': public_lobby(game, chat_id=chat_id, viewer_id=user_id),
                  'role': own_role(game, chat_id=chat_id, user_id=user_id)}
        await self.games.complete_command(command_id, result)
        return result

    async def advance(self, *, chat_id: int, user_id: int,
                      expected_revision: int, command_id: str | None = None) -> dict:
        row = await self._lock(chat_id, user_id)
        if row is None:
            raise LookupError('Партия не найдена.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_user_id=user_id,
            kind='mafia.advance', expected_revision=expected_revision, payload={},
        )
        if cached:
            return result
        status = (row.state if row else {}).get('status')
        transition = resolve_night if status == 'night' else open_voting if status == 'day' else resolve_vote if status == 'voting' else None
        if transition is None:
            raise ValueError('Сейчас партию нельзя продолжить.')
        game = transition(row.state if row else None, chat_id=chat_id, user_id=user_id,
                          expected_revision=expected_revision)
        await self.games.sync_state(row, game, event_kind='phase_advanced', actor_user_id=user_id)
        result = {'lobby': public_lobby(game, chat_id=chat_id, viewer_id=user_id),
                  'role': own_role(game, chat_id=chat_id, user_id=user_id)}
        await self.games.complete_command(command_id, result)
        return result

    async def advance_due(self, *, chat_id: int, now=None) -> dict | None:
        """Advance an expired phase under the same row lock as user commands."""
        row = await self._lock(chat_id)
        game = row.state if row else {}
        if not phase_due(game, now=now):
            return None
        status = game.get('status')
        transition = (resolve_night if status == 'night' else
                      open_voting if status == 'day' else
                      resolve_vote if status == 'voting' else None)
        if transition is None:
            return None
        kwargs = dict(
            chat_id=chat_id,
            user_id=game.get('host_id'),
            expected_revision=game.get('revision'),
            now=now,
        )
        if status in {'night', 'voting'}:
            kwargs['allow_incomplete'] = True
        game = transition(game, **kwargs)
        await self.games.sync_state(row, game, event_kind='deadline_advanced')
        projection = public_lobby(game, chat_id=chat_id, viewer_id=game['host_id'])
        await NotificationQueue.enqueue_in(
            self.session,
            kind='mafia.phase',
            dedupe_key=f'mafia:{row.id}:phase:{game["revision"]}',
            payload={'lobby': projection},
            game_id=row.id,
            chat_id=chat_id,
        )
        return projection

    async def due_chat_ids(self, *, now=None) -> list[int]:
        return await self.games.due_chat_ids(mode='mafia', now=now)

    async def vote(self, *, chat_id: int, user_id: int, target_seat: str,
                   expected_revision: int, command_id: str | None = None) -> dict:
        row = await self._lock(chat_id, user_id)
        if row is None:
            raise LookupError('Партия не найдена.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_user_id=user_id,
            kind='mafia.vote', expected_revision=expected_revision,
            payload={'target_seat': target_seat},
        )
        if cached:
            return result
        game = cast_vote(row.state if row else None, chat_id=chat_id, user_id=user_id,
                         target_seat=target_seat, expected_revision=expected_revision)
        await self.games.sync_state(row, game, event_kind='vote_cast', actor_user_id=user_id)
        result = {'lobby': public_lobby(game, chat_id=chat_id, viewer_id=user_id),
                  'role': own_role(game, chat_id=chat_id, user_id=user_id)}
        await self.games.complete_command(command_id, result)
        return result
