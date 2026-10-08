"""Application commands and projections for the shared Mafia lobby.

This module deliberately knows nothing about Telegram, HTTP or the Mini App UI.
Adapters pass an actor and render the returned projection in their own format.
"""

from functools import wraps

from storage.admin_actions import operation_fence, require_access
from sqlalchemy import select
from domain.mafia import (
    cast_vote,
    join_lobby,
    normalize_discussion_message,
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
from storage.models import ChatMember, Game, GameEvent, Room, RoomMembership
from storage.notifications import NotificationQueue


def _atomic_game_command(method):
    """Keep command receipt, state transition, event and result all-or-nothing.

    HTTP adapters translate domain exceptions into responses before leaving
    their outer transaction. A savepoint here prevents an accepted but
    unfinished idempotency receipt from being committed in that case.
    """
    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        async with self.session.begin_nested():
            return await method(self, *args, **kwargs)
    return wrapped


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
        if row is None:
            return None
        account_id = await self.games.existing_account_for_telegram_user(viewer_id)
        return public_lobby(
            row.state, chat_id=chat_id,
            viewer_account_id=str(account_id) if account_id is not None else None,
        )

    async def _telegram_account(self, user_id: int) -> str:
        return str(await self.games.account_for_telegram_user(user_id))

    async def _read_telegram_account(self, user_id: int) -> str | None:
        account_id = await self.games.existing_account_for_telegram_user(user_id)
        return str(account_id) if account_id is not None else None

    @staticmethod
    def _is_player(state: dict, account_id: str) -> bool:
        return any(player.get('account_id') == account_id for player in state.get('players', [])
                   if isinstance(player, dict))

    async def discussion(self, *, chat_id: int, viewer_id: int, limit: int = 50) -> dict:
        row = await self._read(chat_id)
        if row is None:
            raise LookupError('Стол ещё не создан.')
        account_id = await self._read_telegram_account(viewer_id)
        if not self._is_player(row.state or {}, account_id):
            raise PermissionError('Обсуждение доступно только участникам стола.')
        enabled = row.status in {'lobby', 'day'}
        limit = max(1, min(int(limit), 100))
        rows = (await self.session.scalars(
            select(GameEvent).where(
                GameEvent.game_id == row.id,
                GameEvent.kind == 'discussion_message',
                GameEvent.visibility == 'public',
            ).order_by(GameEvent.event_index.desc()).limit(limit)
        )).all()
        names = {str(player['account_id']): str(player.get('name') or 'Игрок')[:120]
                 for player in (row.state or {}).get('players', [])
                 if isinstance(player, dict) and isinstance(player.get('account_id'), str)}
        return {
            'enabled': enabled,
            'items': [{
                'id': event.event_index,
                'author': names.get(str(event.actor_account_id), 'Игрок'),
                'is_me': str(event.actor_account_id) == account_id,
                'message': event.payload.get('message', ''),
                'created_at': event.created_at.isoformat() if event.created_at else None,
            } for event in reversed(rows)],
        }

    @_atomic_game_command
    async def post_discussion(
        self, *, chat_id: int, user_id: int, message: object,
        command_id: str,
    ) -> dict:
        row = await self._lock(chat_id, user_id)
        if row is None:
            raise LookupError('Стол ещё не создан.')
        account_id = await self._telegram_account(user_id)
        if not self._is_player(row.state or {}, account_id):
            raise PermissionError('Обсуждение доступно только участникам стола.')
        normalized = normalize_discussion_message(message)
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_user_id=user_id,
            actor_account_id=account_id,
            kind='mafia.discussion', expected_revision=None,
            payload={'message': normalized},
        )
        if cached:
            return result
        if row.status not in {'lobby', 'day'}:
            raise ValueError('Обсуждение открыто во время сбора стола и дневной фазы.')
        event = await self.games.append_event(
            row, kind='discussion_message', actor_user_id=user_id,
            actor_account_id=account_id,
            visibility='public', payload={'message': normalized},
        )
        result = {'id': event.event_index, 'accepted': True}
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def join(
        self, *, chat_id: int, user_id: int, name: str,
        command_id: str | None = None,
    ) -> dict:
        row = await self._lock(chat_id, user_id)
        account_id = await self._telegram_account(user_id)
        lobby, changed = join_lobby(
            row.state if row else None, chat_id=chat_id,
            room_id=self.games.telegram_room_id(chat_id) if hasattr(self.games, 'telegram_room_id') else f'telegram:{chat_id}',
            account_id=account_id, name=name,
        )
        if row is None:
            row = await self.games.create_current(chat_id=chat_id, mode='mafia', state=lobby)
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_user_id=user_id,
            actor_account_id=account_id,
            kind='mafia.join', expected_revision=None, payload={'name': name[:120]},
        )
        if cached:
            return result
        if changed and row.state != lobby:
            await self.games.sync_state(
                row, lobby, event_kind='player_joined', actor_user_id=user_id,
                actor_account_id=account_id,
            )
        result = {
            'lobby': public_lobby(lobby, chat_id=chat_id, viewer_account_id=account_id),
            'changed': changed,
        }
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
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
        account_id = await self._telegram_account(user_id)
        if row is None:
            raise LookupError('Лобби ещё не создано.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_user_id=user_id,
            actor_account_id=account_id,
            kind='mafia.ready', expected_revision=expected_revision,
            payload={'ready': ready},
        )
        if cached:
            return result
        lobby = set_ready(
            row.state if row else None,
            chat_id=chat_id,
            account_id=account_id,
            ready=ready,
            expected_revision=expected_revision,
        )
        await self.games.sync_state(row, lobby, event_kind='readiness_changed', actor_user_id=user_id, actor_account_id=account_id)
        result = public_lobby(lobby, chat_id=chat_id, viewer_account_id=account_id)
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def start(
        self, *, chat_id: int, user_id: int, expected_revision: int,
        command_id: str | None = None,
    ) -> dict:
        row = await self._lock(chat_id, user_id)
        account_id = await self._telegram_account(user_id)
        if row is None:
            raise LookupError('Стол не найден.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_user_id=user_id,
            actor_account_id=account_id,
            kind='mafia.start', expected_revision=expected_revision, payload={},
        )
        if cached:
            return result
        lobby = start_lobby(
            row.state if row else None,
            chat_id=chat_id,
            account_id=account_id,
            expected_revision=expected_revision,
        )
        await self.games.sync_state(row, lobby, event_kind='game_started', actor_user_id=user_id, actor_account_id=account_id)
        result = public_lobby(lobby, chat_id=chat_id, viewer_account_id=account_id)
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def restart(
        self, *, chat_id: int, user_id: int, expected_revision: int,
        command_id: str | None = None,
    ) -> dict:
        row = await self._lock(chat_id, user_id)
        account_id = await self._telegram_account(user_id)
        if row is None:
            raise LookupError('Стол не найден.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_user_id=user_id,
            actor_account_id=account_id,
            kind='mafia.restart', expected_revision=expected_revision, payload={},
        )
        if cached:
            return result
        lobby = restart_lobby(
            row.state if row else None,
            chat_id=chat_id,
            account_id=account_id,
            expected_revision=expected_revision,
        )
        await self.games.replace_current(row, state=lobby)
        result = public_lobby(lobby, chat_id=chat_id, viewer_account_id=account_id)
        await self.games.complete_command(command_id, result)
        return result

    async def role(self, *, chat_id: int, user_id: int) -> dict | None:
        row = await self._read(chat_id)
        if row is None:
            return None
        account_id = await self._read_telegram_account(user_id)
        return own_role(row.state, chat_id=chat_id, account_id=account_id)

    @_atomic_game_command
    async def action(self, *, chat_id: int, user_id: int, target_seat: str,
                     expected_revision: int, command_id: str | None = None) -> dict:
        row = await self._lock(chat_id, user_id)
        account_id = await self._telegram_account(user_id)
        if row is None:
            raise LookupError('Партия не найдена.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_user_id=user_id,
            actor_account_id=account_id,
            kind='mafia.action', expected_revision=expected_revision,
            payload={'target_seat': target_seat},
        )
        if cached:
            return result
        game = night_action(row.state if row else None, chat_id=chat_id, account_id=account_id,
                            target_seat=target_seat, expected_revision=expected_revision)
        await self.games.sync_state(row, game, event_kind='night_action', actor_user_id=user_id, actor_account_id=account_id)
        result = {'lobby': public_lobby(game, chat_id=chat_id, viewer_account_id=account_id),
                  'role': own_role(game, chat_id=chat_id, account_id=account_id)}
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def advance(self, *, chat_id: int, user_id: int,
                      expected_revision: int, command_id: str | None = None) -> dict:
        row = await self._lock(chat_id, user_id)
        account_id = await self._telegram_account(user_id)
        if row is None:
            raise LookupError('Партия не найдена.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_user_id=user_id,
            actor_account_id=account_id,
            kind='mafia.advance', expected_revision=expected_revision, payload={},
        )
        if cached:
            return result
        status = (row.state if row else {}).get('status')
        transition = resolve_night if status == 'night' else open_voting if status == 'day' else resolve_vote if status == 'voting' else None
        if transition is None:
            raise ValueError('Сейчас партию нельзя продолжить.')
        game = transition(row.state if row else None, chat_id=chat_id, account_id=account_id,
                          expected_revision=expected_revision)
        await self.games.sync_state(row, game, event_kind='phase_advanced', actor_user_id=user_id, actor_account_id=account_id)
        result = {'lobby': public_lobby(game, chat_id=chat_id, viewer_account_id=account_id),
                  'role': own_role(game, chat_id=chat_id, account_id=account_id)}
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
            account_id=game.get('host_account_id'),
            expected_revision=game.get('revision'), now=now,
        )
        # Legacy Telegram scheduler remains a Bot boundary; domain uses only
        # the already-resolved canonical account identity.
        if status in {'night', 'voting'}:
            kwargs['allow_incomplete'] = True
        game = transition(game, **kwargs)
        await self.games.sync_state(row, game, event_kind='deadline_advanced')
        projection = public_lobby(game, chat_id=chat_id, viewer_account_id=game['host_account_id'])
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

    async def due_game_ids(self, *, now=None) -> list[str]:
        return await self.games.due_game_ids(mode='mafia', now=now)

    async def _room_lock(self, *, room_id: str, account_id):
        """Lock a standalone Mafia room and require active membership."""
        from uuid import UUID

        try:
            account_id = UUID(str(account_id))
        except (TypeError, ValueError, AttributeError):
            raise PermissionError('Нет доступа к этой игровой комнате.') from None
        await operation_fence(self.session)
        # Match GameRepository.create_room_current lock order (logical game
        # key before Room row) to avoid a first-create/command deadlock.
        row = await self.games.current_in_room(
            room_id=room_id, mode='mafia', lock=True,
        )
        room = await self.session.scalar(select(Room).where(
            Room.id == room_id, Room.kind == 'standalone',
        ).with_for_update())
        member = await self.session.get(RoomMembership, (room_id, account_id))
        if room is None or member is None or member.status != 'active':
            raise LookupError('Игровая комната не найдена.')
        return row, room, member

    async def room_lobby(self, *, room_id: str, account_id) -> dict | None:
        from uuid import UUID

        account_id = str(UUID(str(account_id)))
        row, _, _ = await self._room_lock(room_id=room_id, account_id=account_id)
        if row is None:
            return None
        return public_lobby(
            row.state, room_id=room_id, viewer_account_id=str(account_id),
        )

    @_atomic_game_command
    async def create_room_lobby(
        self, *, room_id: str, account_id, name: str,
        command_id: str,
    ) -> dict:
        row, room, membership = await self._room_lock(
            room_id=room_id, account_id=account_id,
        )
        from uuid import UUID
        account_id = str(UUID(str(account_id)))
        if room.owner_account_id != UUID(account_id) or membership.role != 'owner':
            raise PermissionError('Стол может создать только владелец комнаты.')
        if row is not None:
            # A retry returns its receipt below; a different command must not
            # silently replace the existing lobby.
            cached, result = await self.games.reserve_command(
                command_id=command_id, game_id=row.id, actor_account_id=account_id,
                kind='mafia.room.create', expected_revision=None,
                payload={'room_id': room_id},
            )
            if cached:
                return result
            raise ValueError('Стол в этой комнате уже создан.')
        from domain.mafia import new_room_lobby
        lobby = new_room_lobby(room_id, account_id, name)
        row = await self.games.create_room_current(
            room_id=room_id, mode='mafia', state=lobby,
            actor_account_id=account_id,
        )
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_account_id=account_id,
            kind='mafia.room.create', expected_revision=None,
            payload={'room_id': room_id},
        )
        if cached:
            return result
        result = public_lobby(lobby, room_id=room_id, viewer_account_id=account_id)
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def room_join(
        self, *, room_id: str, account_id, name: str, command_id: str,
    ) -> dict:
        row, _, _ = await self._room_lock(room_id=room_id, account_id=account_id)
        from uuid import UUID
        account_id = str(UUID(str(account_id)))
        if row is None:
            raise LookupError('Стол ещё не создан.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_account_id=account_id,
            kind='mafia.join', expected_revision=None, payload={'name': name[:120]},
        )
        if cached:
            return result
        lobby, changed = join_lobby(
            row.state, room_id=room_id, account_id=account_id, name=name,
        )
        if changed:
            await self.games.sync_state(
                row, lobby, event_kind='player_joined', actor_account_id=account_id,
            )
        result = public_lobby(lobby, room_id=room_id, viewer_account_id=account_id)
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def room_ready(
        self, *, room_id: str, account_id, ready: bool,
        expected_revision: int, command_id: str,
    ) -> dict:
        row, _, _ = await self._room_lock(room_id=room_id, account_id=account_id)
        from uuid import UUID
        account_id = str(UUID(str(account_id)))
        if row is None:
            raise LookupError('Лобби ещё не создано.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_account_id=account_id,
            kind='mafia.ready', expected_revision=expected_revision,
            payload={'ready': ready},
        )
        if cached:
            return result
        lobby = set_ready(
            row.state, room_id=room_id, account_id=account_id,
            ready=ready, expected_revision=expected_revision,
        )
        await self.games.sync_state(
            row, lobby, event_kind='readiness_changed', actor_account_id=account_id,
        )
        result = public_lobby(lobby, room_id=room_id, viewer_account_id=account_id)
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def room_start(
        self, *, room_id: str, account_id, expected_revision: int,
        command_id: str,
    ) -> dict:
        row, _, _ = await self._room_lock(room_id=room_id, account_id=account_id)
        from uuid import UUID
        account_id = str(UUID(str(account_id)))
        if row is None:
            raise LookupError('Стол ещё не создан.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_account_id=account_id,
            kind='mafia.start', expected_revision=expected_revision, payload={},
        )
        if cached:
            return result
        lobby = start_lobby(
            row.state, room_id=room_id, account_id=account_id,
            expected_revision=expected_revision,
        )
        await self.games.sync_state(
            row, lobby, event_kind='game_started', actor_account_id=account_id,
        )
        result = public_lobby(lobby, room_id=room_id, viewer_account_id=account_id)
        await self.games.complete_command(command_id, result)
        return result

    async def room_role(self, *, room_id: str, account_id) -> dict | None:
        row, _, _ = await self._room_lock(room_id=room_id, account_id=account_id)
        if row is None:
            return None
        return own_role(row.state, room_id=room_id, account_id=str(account_id))

    async def room_discussion(self, *, room_id: str, account_id, limit: int = 50) -> dict:
        from uuid import UUID

        account_id = str(UUID(str(account_id)))
        row, _, _ = await self._room_lock(room_id=room_id, account_id=account_id)
        if row is None:
            raise LookupError('Стол ещё не создан.')
        if not any(player.get('account_id') == account_id
                   for player in (row.state or {}).get('players', [])
                   if isinstance(player, dict)):
            raise PermissionError('Обсуждение доступно только участникам стола.')
        enabled = row.status in {'lobby', 'day'}
        limit = max(1, min(int(limit), 100))
        events = (await self.session.scalars(
            select(GameEvent).where(
                GameEvent.game_id == row.id,
                GameEvent.kind == 'discussion_message',
                GameEvent.visibility == 'public',
            ).order_by(GameEvent.event_index.desc()).limit(limit)
        )).all()
        names = {player['account_id']: str(player.get('name') or 'Игрок')[:120]
                 for player in (row.state or {}).get('players', [])
                 if isinstance(player, dict) and isinstance(player.get('account_id'), str)}
        return {'enabled': enabled, 'items': [{
            'id': event.event_index,
            'author': names.get(str(event.actor_account_id), 'Игрок'),
            'is_me': event.actor_account_id == UUID(account_id),
            'message': event.payload.get('message', ''),
            'created_at': event.created_at.isoformat() if event.created_at else None,
        } for event in reversed(events)]}

    @_atomic_game_command
    async def room_post_discussion(
        self, *, room_id: str, account_id, message: object, command_id: str,
    ) -> dict:
        from uuid import UUID

        account_id = str(UUID(str(account_id)))
        row, _, _ = await self._room_lock(room_id=room_id, account_id=account_id)
        if row is None:
            raise LookupError('Стол ещё не создан.')
        if not any(player.get('account_id') == account_id
                   for player in (row.state or {}).get('players', [])
                   if isinstance(player, dict)):
            raise PermissionError('Обсуждение доступно только участникам стола.')
        normalized = normalize_discussion_message(message)
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_account_id=account_id,
            kind='mafia.discussion', expected_revision=None,
            payload={'message': normalized},
        )
        if cached:
            return result
        if row.status not in {'lobby', 'day'}:
            raise ValueError('Обсуждение открыто во время сбора стола и дневной фазы.')
        event = await self.games.append_event(
            row, kind='discussion_message', actor_user_id=None,
            actor_account_id=account_id, visibility='public',
            payload={'message': normalized},
        )
        result = {'id': event.event_index, 'accepted': True}
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def room_action(
        self, *, room_id: str, account_id, target_seat: str,
        expected_revision: int, command_id: str,
    ) -> dict:
        from uuid import UUID

        account_id = str(UUID(str(account_id)))
        row, _, _ = await self._room_lock(room_id=room_id, account_id=account_id)
        if row is None:
            raise LookupError('Партия не найдена.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_account_id=account_id,
            kind='mafia.action', expected_revision=expected_revision,
            payload={'target_seat': target_seat},
        )
        if cached:
            return result
        game = night_action(
            row.state, room_id=room_id, account_id=account_id,
            target_seat=target_seat, expected_revision=expected_revision,
        )
        await self.games.sync_state(
            row, game, event_kind='night_action', actor_account_id=account_id,
        )
        result = {
            'lobby': public_lobby(game, room_id=room_id, viewer_account_id=account_id),
            'role': own_role(game, room_id=room_id, account_id=account_id),
        }
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def room_vote(
        self, *, room_id: str, account_id, target_seat: str,
        expected_revision: int, command_id: str,
    ) -> dict:
        from uuid import UUID

        account_id = str(UUID(str(account_id)))
        row, _, _ = await self._room_lock(room_id=room_id, account_id=account_id)
        if row is None:
            raise LookupError('Партия не найдена.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_account_id=account_id,
            kind='mafia.vote', expected_revision=expected_revision,
            payload={'target_seat': target_seat},
        )
        if cached:
            return result
        game = cast_vote(
            row.state, room_id=room_id, account_id=account_id,
            target_seat=target_seat, expected_revision=expected_revision,
        )
        await self.games.sync_state(
            row, game, event_kind='vote_cast', actor_account_id=account_id,
        )
        result = {
            'lobby': public_lobby(game, room_id=room_id, viewer_account_id=account_id),
            'role': own_role(game, room_id=room_id, account_id=account_id),
        }
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def room_advance(
        self, *, room_id: str, account_id, expected_revision: int,
        command_id: str,
    ) -> dict:
        from uuid import UUID

        account_id = str(UUID(str(account_id)))
        row, _, _ = await self._room_lock(room_id=room_id, account_id=account_id)
        if row is None:
            raise LookupError('Партия не найдена.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_account_id=account_id,
            kind='mafia.advance', expected_revision=expected_revision, payload={},
        )
        if cached:
            return result
        status = row.state.get('status')
        transition = (resolve_night if status == 'night' else
                      open_voting if status == 'day' else
                      resolve_vote if status == 'voting' else None)
        if transition is None:
            raise ValueError('Сейчас партию нельзя продолжить.')
        game = transition(
            row.state, room_id=room_id, account_id=account_id,
            expected_revision=expected_revision,
        )
        await self.games.sync_state(
            row, game, event_kind='phase_advanced', actor_account_id=account_id,
        )
        result = {
            'lobby': public_lobby(game, room_id=room_id, viewer_account_id=account_id),
            'role': own_role(game, room_id=room_id, account_id=account_id),
        }
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def room_restart(
        self, *, room_id: str, account_id, expected_revision: int,
        command_id: str,
    ) -> dict:
        from uuid import UUID

        account_id = str(UUID(str(account_id)))
        row, _, _ = await self._room_lock(room_id=room_id, account_id=account_id)
        if row is None:
            raise LookupError('Стол не найден.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_account_id=account_id,
            kind='mafia.restart', expected_revision=expected_revision, payload={},
        )
        if cached:
            return result
        lobby = restart_lobby(
            row.state, room_id=room_id, account_id=account_id,
            expected_revision=expected_revision,
        )
        await self.games.replace_current(row, state=lobby)
        projection = public_lobby(
            lobby, room_id=room_id, viewer_account_id=account_id,
        )
        result = {'lobby': projection}
        await self.games.complete_command(command_id, result)
        return result

    async def advance_due_game(self, *, game_id: str, now=None) -> dict | None:
        """Advance a due Mafia game by platform game identity, not transport ID."""
        await operation_fence(self.session)
        candidate = await self.session.get(Game, game_id)
        if candidate is None or not candidate.is_current or candidate.mode != 'mafia':
            return None
        if candidate.chat_id is None:
            row = await self.games.current_in_room(
                room_id=candidate.room_id, mode='mafia', lock=True,
            )
        else:
            row = await self.games.current(
                chat_id=candidate.chat_id, mode='mafia', lock=True,
            )
        if row is None or row.id != game_id:
            return None
        game = row.state or {}
        if not phase_due(game, now=now):
            return None
        status = game.get('status')
        transition = (resolve_night if status == 'night' else
                      open_voting if status == 'day' else
                      resolve_vote if status == 'voting' else None)
        if transition is None:
            return None
        if row.chat_id is None:
            room_id = row.room_id
            host_id = game.get('host_account_id')
            kwargs = dict(room_id=room_id, account_id=host_id)
        else:
            room_id = row.room_id
            host_id = game.get('host_account_id')
            kwargs = dict(chat_id=row.chat_id, room_id=room_id, account_id=host_id)
        kwargs.update(expected_revision=game.get('revision'), now=now)
        if status in {'night', 'voting'}:
            kwargs['allow_incomplete'] = True
        game = transition(game, **kwargs)
        await self.games.sync_state(row, game, event_kind='deadline_advanced')
        projection = public_lobby(game, chat_id=row.chat_id, room_id=room_id,
                                  viewer_account_id=host_id)
        if row.chat_id is not None:
            await NotificationQueue.enqueue_in(
                self.session,
                kind='mafia.phase',
                dedupe_key=f'mafia:{row.id}:phase:{game["revision"]}',
                payload={'lobby': projection},
                game_id=row.id,
                chat_id=row.chat_id,
            )
        return projection

    @_atomic_game_command
    async def vote(self, *, chat_id: int, user_id: int, target_seat: str,
                   expected_revision: int, command_id: str | None = None) -> dict:
        row = await self._lock(chat_id, user_id)
        account_id = await self._telegram_account(user_id)
        if row is None:
            raise LookupError('Партия не найдена.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_user_id=user_id,
            actor_account_id=account_id,
            kind='mafia.vote', expected_revision=expected_revision,
            payload={'target_seat': target_seat},
        )
        if cached:
            return result
        game = cast_vote(row.state if row else None, chat_id=chat_id, account_id=account_id,
                         target_seat=target_seat, expected_revision=expected_revision)
        await self.games.sync_state(row, game, event_kind='vote_cast', actor_user_id=user_id, actor_account_id=account_id)
        result = {'lobby': public_lobby(game, chat_id=chat_id, viewer_account_id=account_id),
                  'role': own_role(game, chat_id=chat_id, account_id=account_id)}
        await self.games.complete_command(command_id, result)
        return result
