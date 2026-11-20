"""Application commands and projections for the shared Mafia lobby.

This module deliberately knows nothing about Telegram, HTTP or the Mini App UI.
Adapters pass an actor and render the returned projection in their own format.
"""

from datetime import datetime, timezone
from functools import wraps
from uuid import UUID

from storage.admin_actions import operation_fence, require_access
from sqlalchemy import String, cast, select
from domain.mafia import (
    LOBBY_IDLE_SECONDS,
    cast_vote,
    discussion_access,
    join_lobby,
    normalize_discussion_message,
    night_action,
    open_voting,
    own_role,
    phase_complete,
    phase_due,
    public_lobby,
    remove_player,
    resolve_night,
    resolve_vote,
    restart_lobby,
    set_portrait,
    set_world,
    leave_table,
    set_ready,
    start_lobby,
    unseat_lobby,
    wait_lobby,
)
from domain.night_worlds import require_age_ok
from storage.games import GameRepository
from sqlalchemy import func, text, update
from application import room_limits
from application.rooms import RoomApplicationService
from storage.models import (Account, AccountIdentity, ChatMember, Game, GameEvent, Room,
                            RoomInvite, RoomMembership, User)
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
        may_read, may_post = discussion_access(row.state, chat_id=chat_id, account_id=account_id)
        if not may_read:
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
            'can_post': enabled and may_post,
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
        may_read, may_post = discussion_access(row.state, chat_id=chat_id, account_id=account_id)
        if not may_read:
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
        if not may_post:
            raise PermissionError('Выбывшие игроки только читают обсуждение.')
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
        game = await self._close_if_complete(row)
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

    @staticmethod
    def _transition_for(status):
        return (resolve_night if status == 'night' else
                open_voting if status == 'day' else
                resolve_vote if status == 'voting' else None)

    async def _advance_phase(self, row, game: dict, *, event_kind: str, now=None,
                             allow_incomplete: bool = False, skip_account_id=None) -> dict | None:
        """The one phase-transition path: deadline worker and early close both go through here.

        Runs under the caller's game lock. Notifications are deduplicated per game and phase
        revision, so a deadline racing an early close (or a replay) never sends a second message.
        """
        transition = self._transition_for(game.get('status'))
        if transition is None:
            return None
        kwargs = dict(room_id=row.room_id, account_id=game.get('host_account_id'),
                      expected_revision=game.get('revision'), now=now)
        if row.chat_id is not None:
            kwargs['chat_id'] = row.chat_id
        if game.get('status') in {'night', 'voting'}:
            kwargs['allow_incomplete'] = allow_incomplete
        advanced = transition(game, **kwargs)
        await self.games.sync_state(row, advanced, event_kind=event_kind)
        if row.chat_id is not None:
            await NotificationQueue.enqueue_in(
                self.session, kind='mafia.phase',
                dedupe_key=f'mafia:{row.id}:phase:{advanced["revision"]}',
                payload={'lobby': public_lobby(advanced, chat_id=row.chat_id, room_id=row.room_id,
                                               viewer_account_id=advanced['host_account_id'])},
                game_id=row.id, chat_id=row.chat_id,
            )
        else:
            await self._notify_room_phase(row, advanced, skip_account_id=skip_account_id)
        return advanced

    async def _close_if_complete(self, row, *, skip_account_id=None) -> dict:
        """Early close: all living night roles acted / all living players voted."""
        game = row.state
        if phase_complete(game):
            advanced = await self._advance_phase(row, game, event_kind='early_advanced',
                                                 skip_account_id=skip_account_id)
            if advanced is not None:
                return advanced
        return game

    @staticmethod
    def _touch_open(room, now=None) -> None:
        RoomApplicationService.touch_open(room, now)

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

    ROOM_PHASE_KIND = 'mafia.room_phase'
    ROOM_PHASE_STATUSES = frozenset({'night', 'day', 'voting', 'finished'})

    async def _notify_room_phase(self, row, game: dict, *, skip_account_id=None) -> int:
        """Queue one private Telegram nudge per Telegram-linked player of a room game.

        The payload carries only public data (room title, phase, round): no roles, targets or
        votes. A player without a verified Telegram identity gets nothing (the app is the
        channel for them). ``skip_account_id`` is the actor who just saw the change in the app.
        Dedupe is per game, phase revision and Telegram user, so a replayed command or a
        deadline racing a manual advance never produces a second message.
        """
        status = game.get('status')
        if row.chat_id is not None or status not in self.ROOM_PHASE_STATUSES:
            return 0
        accounts = set()
        for player in game.get('players', []):
            value = player.get('account_id') if isinstance(player, dict) else None
            if value is not None and str(value) != str(skip_account_id):
                accounts.add(UUID(str(value)))
        if accounts:
            # Whoever left or was removed from the room is not nudged about its table.
            accounts = set((await self.session.scalars(select(RoomMembership.account_id).where(
                RoomMembership.room_id == row.room_id, RoomMembership.status == 'active',
                RoomMembership.account_id.in_(accounts)))).all())
        if not accounts:
            return 0
        user_ids = (await self.session.scalars(
            select(User.id).join(Account, Account.id == User.account_id)
            .join(AccountIdentity, AccountIdentity.account_id == User.account_id)
            .where(
                User.account_id.in_(accounts), User.archived.is_(False), User.bot_blocked.is_(False),
                Account.archived.is_(False), Account.bot_blocked.is_(False),
                AccountIdentity.provider == 'telegram',
                AccountIdentity.provider_subject == cast(User.id, String),
                AccountIdentity.revoked_at.is_(None), AccountIdentity.verified_at.is_not(None),
            ).order_by(User.id)
        )).all()
        if not user_ids:
            return 0
        room = await self.session.get(Room, row.room_id)
        payload = {
            'room_id': row.room_id, 'room_title': (room.title if room else '')[:80],
            'status': status, 'round': game.get('round'),
            'phase_revision': game.get('phase_revision'),
        }
        queued = 0
        for user_id in user_ids:
            queued += await NotificationQueue.enqueue_in(
                self.session, kind=self.ROOM_PHASE_KIND,
                dedupe_key=f'mafia:{row.id}:roomphase:{game.get("phase_revision")}:{user_id}',
                payload=payload, game_id=row.id, chat_id=user_id, user_id=user_id,
            )
        return queued

    async def room_phase_is_current(self, *, game_id: str, phase_revision) -> bool:
        """Delivery-time check: a queued nudge for an already superseded phase is dropped."""
        row = await self.session.get(Game, game_id)
        return bool(row is not None and row.is_current and row.mode == 'mafia'
                    and (row.state or {}).get('phase_revision') == phase_revision)

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
        lobby = new_room_lobby(room_id, account_id, name, room.world)
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
        self._touch_open(room)
        result = public_lobby(lobby, room_id=room_id, viewer_account_id=account_id)
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def room_join(
        self, *, room_id: str, account_id, name: str, command_id: str,
    ) -> dict:
        row, room, _ = await self._room_lock(room_id=room_id, account_id=account_id)
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
            self._touch_open(room)
        result = public_lobby(lobby, room_id=room_id, viewer_account_id=account_id)
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def room_ready(
        self, *, room_id: str, account_id, ready: bool,
        expected_revision: int, command_id: str,
    ) -> dict:
        row, room, _ = await self._room_lock(room_id=room_id, account_id=account_id)
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
        self._touch_open(room)
        result = public_lobby(lobby, room_id=room_id, viewer_account_id=account_id)
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def room_start(
        self, *, room_id: str, account_id, expected_revision: int,
        command_id: str,
    ) -> dict:
        row, room, _ = await self._room_lock(room_id=room_id, account_id=account_id)
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
        await self._notify_room_phase(row, lobby, skip_account_id=account_id)
        self._touch_open(room)
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
        may_read, may_post = discussion_access(row.state, room_id=room_id, account_id=account_id)
        if not may_read:
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
        return {'enabled': enabled, 'can_post': enabled and may_post, 'items': [{
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
        may_read, may_post = discussion_access(row.state, room_id=room_id, account_id=account_id)
        if not may_read:
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
        if not may_post:
            raise PermissionError('Выбывшие игроки только читают обсуждение.')
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
        game = await self._close_if_complete(row, skip_account_id=account_id)
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
        game = await self._close_if_complete(row, skip_account_id=account_id)
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
        row, room, _ = await self._room_lock(room_id=room_id, account_id=account_id)
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
        await self._notify_room_phase(row, game, skip_account_id=account_id)
        self._touch_open(room)
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
        row, room, _ = await self._room_lock(room_id=room_id, account_id=account_id)
        if row is None:
            raise LookupError('Стол не найден.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_account_id=account_id,
            kind='mafia.restart', expected_revision=expected_revision, payload={},
        )
        if cached:
            return result
        # The finished roster is history. Only current room members return to the new
        # lobby (together with those who waited); Room is locked by _room_lock, also used by leave/join.
        active_accounts = set(str(value) for value in (await self.session.scalars(
            select(RoomMembership.account_id).where(
                RoomMembership.room_id == room_id, RoomMembership.status == 'active',
            )
        )).all())
        lobby = restart_lobby(
            row.state, room_id=room_id, account_id=account_id,
            expected_revision=expected_revision, active_accounts=active_accounts,
        )
        self._touch_open(room)
        await self.games.replace_current(row, state=lobby)
        projection = public_lobby(
            lobby, room_id=room_id, viewer_account_id=account_id,
        )
        result = {'lobby': projection}
        await self.games.complete_command(command_id, result)
        return result

    async def stale_lobby_ids(self, *, now=None) -> list[str]:
        return await self.games.stale_lobby_ids(mode='mafia', idle_seconds=LOBBY_IDLE_SECONDS, now=now)

    async def expire_stale_lobby(self, *, game_id: str, now=None) -> bool:
        """Close a table that gathered players and then stood still for a day; rechecked under the lock."""
        await operation_fence(self.session)
        candidate = await self.session.get(Game, game_id)
        if candidate is None or not candidate.is_current or candidate.mode != 'mafia':
            return False
        if candidate.chat_id is None:
            row = await self.games.current_in_room(room_id=candidate.room_id, mode='mafia', lock=True)
        else:
            row = await self.games.current(chat_id=candidate.chat_id, mode='mafia', lock=True)
        if row is None or row.id != game_id or row.status != 'lobby':
            return False
        if game_id not in await self.stale_lobby_ids(now=now):
            return False
        await self.games.interrupt(row, event_kind='lobby_expired')
        return True

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
        host_id = game.get('host_account_id')
        advanced = await self._advance_phase(
            row, game, event_kind='deadline_advanced', now=now, allow_incomplete=True)
        if advanced is None:
            return None
        return public_lobby(advanced, chat_id=row.chat_id, room_id=row.room_id,
                            viewer_account_id=host_id)

    # --- open rooms: enter without a code, wait for the next game, stand up, remove, portrait

    @_atomic_game_command
    async def room_join_open(self, *, room_id: str, account_id, name: str, command_id: str,
                             now: datetime | None = None, age_ok: bool = False) -> dict:
        """Enter an open room (membership) and take a seat, or wait for the next game.

        Membership, the seat/waiting place and the rate-limit charge are one all-or-nothing
        command under the game lock, so two people racing for the last seat cannot both win
        and a refused entry leaves no membership behind.
        """
        account_uuid = UUID(str(account_id))
        account_id = str(account_uuid)
        current = now or datetime.now(timezone.utc)
        await operation_fence(self.session)
        row = await self.games.current_in_room(room_id=room_id, mode='mafia', lock=True)
        room = await self.session.scalar(select(Room).where(
            Room.id == room_id, Room.kind == 'standalone',
        ).with_for_update())
        if room is None or not RoomApplicationService.open_is_fresh(room, current):
            raise LookupError('Эта комната сейчас не открыта.')
        if row is None:
            raise LookupError('За этим столом ещё никто не сел.')
        membership = await self.session.scalar(select(RoomMembership).where(
            RoomMembership.room_id == room_id, RoomMembership.account_id == account_uuid,
        ).with_for_update().execution_options(populate_existing=True))
        if membership is not None and membership.status == 'removed':
            raise PermissionError('Хозяин убрал тебя из этой комнаты. Вернуться можно только по приглашению.')
        if membership is None or membership.status != 'active':
            require_age_ok(room.world, age_ok)       # a new player of an 18+ world confirms it (not stored)
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_account_id=account_id,
            kind='mafia.join_open', expected_revision=None, payload={},
        )
        if cached:
            return result
        if (row.state or {}).get('status') == 'lobby':
            lobby, changed = join_lobby(row.state, room_id=room_id, account_id=account_id, name=name)
            seat, event_kind = 'seated', 'player_joined'
        else:
            lobby, changed = wait_lobby(row.state, room_id=room_id, account_id=account_id, name=name)
            seat, event_kind = 'waiting', 'player_waiting'
        is_new = membership is None or membership.status != 'active'
        if is_new:
            await room_limits.charge_membership(self.session, account_uuid, current)
            if membership is None:
                membership = RoomMembership(room_id=room_id, account_id=account_uuid,
                                            role='member', status='active')
                self.session.add(membership)
            else:
                membership.role, membership.status = 'member', 'active'
                membership.updated_at = func.greatest(
                    func.clock_timestamp(), RoomMembership.updated_at + text("interval '1 microsecond'"))
            await self.session.flush()
            await self.session.refresh(membership, ['updated_at'])
        if changed:
            await self.games.sync_state(row, lobby, event_kind=event_kind, actor_account_id=account_id)
        RoomApplicationService.touch_open(room, current)
        result = {
            'room': RoomApplicationService.projection(room, membership),
            'joined': is_new, 'seat': seat,
            'lobby': public_lobby(lobby, room_id=room_id, viewer_account_id=account_id),
        }
        await self.games.complete_command(command_id, result)
        return result

    async def _room_table_command(self, *, room_id, account_id, command_id, kind, payload,
                                  expected_revision=None, owner_only=False):
        """Shared prologue of member commands on the current table (lock, receipt)."""
        row, room, membership = await self._room_lock(room_id=room_id, account_id=account_id)
        account_id = str(UUID(str(account_id)))
        if row is None:
            raise LookupError('Стол ещё не создан.')
        if owner_only and (room.owner_account_id != UUID(account_id) or membership.role != 'owner'):
            raise PermissionError('Это может сделать только хозяин комнаты.')
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=row.id, actor_account_id=account_id,
            kind=kind, expected_revision=expected_revision, payload=payload,
        )
        return row, room, account_id, (result if cached else None), cached

    async def leave_table(self, row, room, account_id) -> dict:
        """Table part of leaving the room; runs under the caller's game, room and membership locks.

        Unseats / dequeues, or removes a living hero from a running game (history event, win check,
        early close of the phase when the leaver was the last missing actor, shared notifications).
        """
        account_id = str(UUID(str(account_id)))
        game, outcome, _ = leave_table(row.state, room_id=row.room_id, account_id=account_id)
        if outcome in {'unseated', 'waiting'}:
            await self.games.sync_state(row, game, event_kind='player_left_table',
                                        actor_account_id=account_id)
        elif outcome == 'vanished':
            await self.games.sync_state(row, game, event_kind='player_vanished',
                                        actor_account_id=account_id)
            if game['status'] == 'finished':
                await self._notify_room_phase(row, game, skip_account_id=account_id)
            else:
                await self._close_if_complete(row, skip_account_id=account_id)
        if outcome != 'none':
            self._touch_open(room)
        return {'outcome': outcome}

    @_atomic_game_command
    async def room_wait(self, *, room_id: str, account_id, name: str, command_id: str) -> dict:
        """«Ждать следующую»: a room member sits out the running game and joins the rematch."""
        row, room, account_id, result, cached = await self._room_table_command(
            room_id=room_id, account_id=account_id, command_id=command_id,
            kind='mafia.wait', payload={})
        if cached:
            return result
        lobby, changed = wait_lobby(row.state, room_id=room_id, account_id=account_id, name=name)
        if changed:
            await self.games.sync_state(row, lobby, event_kind='player_waiting', actor_account_id=account_id)
            self._touch_open(room)
        result = public_lobby(lobby, room_id=room_id, viewer_account_id=account_id)
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def room_unseat(self, *, room_id: str, account_id, command_id: str) -> dict:
        """Stand up from an unstarted table or cancel waiting (never during one's own running game)."""
        row, room, account_id, result, cached = await self._room_table_command(
            room_id=room_id, account_id=account_id, command_id=command_id,
            kind='mafia.unseat', payload={})
        if cached:
            return result
        lobby, changed = unseat_lobby(row.state, room_id=room_id, account_id=account_id)
        if changed:
            await self.games.sync_state(row, lobby, event_kind='player_left_table', actor_account_id=account_id)
        result = public_lobby(lobby, room_id=room_id, viewer_account_id=account_id)
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def room_remove_player(self, *, room_id: str, account_id, target: str,
                                 expected_revision: int, command_id: str) -> dict:
        """The owner removes a player from the lobby / waiting list and from the room.

        The removed account gets membership status ``removed``: it can come back only with an
        invitation (link or code); the open list does not let it in.
        """
        row, room, account_id, result, cached = await self._room_table_command(
            room_id=room_id, account_id=account_id, command_id=command_id,
            kind='mafia.remove', expected_revision=expected_revision,
            payload={'target': target}, owner_only=True)
        if cached:
            return result
        lobby, removed_id, _ = remove_player(
            row.state, room_id=room_id, account_id=account_id, target=target,
            expected_revision=expected_revision)
        removed = await self.session.scalar(select(RoomMembership).where(
            RoomMembership.room_id == room_id, RoomMembership.account_id == UUID(removed_id),
        ).with_for_update().execution_options(populate_existing=True))
        if removed is not None and removed.role != 'owner':
            removed.status = 'removed'
            removed.updated_at = func.greatest(
                func.clock_timestamp(), RoomMembership.updated_at + text("interval '1 microsecond'"))
            # Every standing invitation (link or short code) may have been passed on to the removed
            # player or their friends: the host hands out new ones. Room is locked by _room_lock.
            await self.session.execute(update(RoomInvite).where(
                RoomInvite.room_id == room_id, RoomInvite.revoked_at.is_(None),
            ).values(revoked_at=func.now()))
        await self.games.sync_state(row, lobby, event_kind='player_removed', actor_account_id=account_id)
        self._touch_open(room)
        result = public_lobby(lobby, room_id=room_id, viewer_account_id=account_id)
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def room_portrait(self, *, room_id: str, account_id, portrait: int,
                            expected_revision: int, command_id: str) -> dict:
        row, room, account_id, result, cached = await self._room_table_command(
            room_id=room_id, account_id=account_id, command_id=command_id,
            kind='mafia.portrait', expected_revision=expected_revision,
            payload={'portrait': portrait})
        if cached:
            return result
        lobby = set_portrait(row.state, room_id=room_id, account_id=account_id,
                             portrait=portrait, expected_revision=expected_revision)
        await self.games.sync_state(row, lobby, event_kind='portrait_changed', actor_account_id=account_id)
        result = public_lobby(lobby, room_id=room_id, viewer_account_id=account_id)
        await self.games.complete_command(command_id, result)
        return result

    @_atomic_game_command
    async def room_set_world(self, *, room_id: str, account_id, world: str,
                             expected_revision: int, command_id: str) -> dict:
        """The host picks the story of the room (lobby only). The room column and the table state change together."""
        row, room, account_id, result, cached = await self._room_table_command(
            room_id=room_id, account_id=account_id, command_id=command_id,
            kind='mafia.world', expected_revision=expected_revision,
            payload={'world': world}, owner_only=True)
        if cached:
            return result
        lobby = set_world(row.state, room_id=room_id, account_id=account_id,
                          world=world, expected_revision=expected_revision)
        if lobby != row.state:
            await self.games.sync_state(row, lobby, event_kind='world_changed', actor_account_id=account_id)
        room.world = world
        await self.session.flush()
        self._touch_open(room)
        membership = await self.session.get(RoomMembership, (room_id, UUID(account_id)))
        result = {'room': RoomApplicationService.projection(room, membership),
                  'lobby': public_lobby(lobby, room_id=room_id, viewer_account_id=account_id)}
        await self.games.complete_command(command_id, result)
        return result

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
        game = await self._close_if_complete(row)
        result = {'lobby': public_lobby(game, chat_id=chat_id, viewer_account_id=account_id),
                  'role': own_role(game, chat_id=chat_id, account_id=account_id)}
        await self.games.complete_command(command_id, result)
        return result
