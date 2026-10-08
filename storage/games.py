"""Persistence primitives for versioned, long-running game modes."""

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import String, cast, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from .models import (
    Account, AccountIdentity, Chat, Game, GameCommand, GameDeadline, GameEvent,
    GamePlayer, Room, RoomTransport, User,
)


def telegram_room_id(chat_id: int) -> str:
    """Stable room identity for the legacy Telegram-backed game boundary."""
    return f'telegram:{int(chat_id)}'


def _deadline(value):
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if type(value) not in {int, float}:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


class GameRepository:
    """All adapters share these locks and projections; no transport state lives here."""

    def __init__(self, session):
        self.session = session

    @staticmethod
    def telegram_room_id(chat_id: int) -> str:
        return telegram_room_id(chat_id)

    async def account_for_telegram_user(self, user_id: int):
        """Resolve the platform actor while retaining its verified Telegram link."""
        user = await self.session.scalar(
            select(User).where(User.id == user_id).with_for_update()
        )
        if user is None:
            raise LookupError('Игрок не найден.')
        subject = str(user_id)
        historical_identity = await self.session.scalar(select(AccountIdentity).where(
            AccountIdentity.provider == 'telegram',
            AccountIdentity.provider_subject == subject,
        ).order_by(AccountIdentity.revoked_at.is_(None).desc()).limit(1).with_for_update())
        if historical_identity is not None and historical_identity.revoked_at is not None:
            raise RuntimeError('Telegram identity was revoked; explicit recovery is required.')
        if user.account_id is None:
            account = Account(display_name=(user.display_name or 'Игрок')[:255])
            self.session.add(account)
            await self.session.flush()
            user.account_id = account.id
            await self.session.flush()

        identity = historical_identity
        if identity is not None and identity.account_id != user.account_id:
            raise RuntimeError('Telegram identity points to a different platform account.')
        if identity is None:
            now = datetime.now(timezone.utc)
            self.session.add(AccountIdentity(
                account_id=user.account_id, provider='telegram', provider_subject=subject,
                verified_at=now, linked_at=now,
            ))
            await self.session.flush()
        return user.account_id

    async def existing_account_for_telegram_user(self, user_id: int):
        """Read an already-provisioned Telegram account without creating identity rows."""
        user = await self.session.scalar(select(User).where(User.id == user_id))
        if user is None or user.account_id is None:
            return None
        identity = await self.session.scalar(select(AccountIdentity).where(
            AccountIdentity.provider == 'telegram',
            AccountIdentity.provider_subject == str(user_id),
            AccountIdentity.revoked_at.is_(None),
        ))
        if identity is not None and identity.account_id != user.account_id:
            raise RuntimeError('Telegram identity points to a different platform account.')
        if identity is None or identity.verified_at is None:
            return None
        return identity.account_id

    async def _resolve_actor_account(
        self, *, actor_user_id: int | None, actor_account_id=None,
    ):
        """Resolve an event/command actor without requiring a Telegram identity."""
        if actor_account_id is not None:
            try:
                actor_account_id = UUID(str(actor_account_id))
            except (TypeError, ValueError, AttributeError):
                raise ValueError('Некорректный игровой аккаунт.') from None
        if actor_user_id is not None:
            linked = await self.account_for_telegram_user(actor_user_id)
            if actor_account_id is not None and linked != actor_account_id:
                raise RuntimeError('Telegram identity points to a different platform account.')
            return linked
        if actor_account_id is None:
            return None
        account = await self.session.get(Account, actor_account_id)
        if account is None:
            raise LookupError('Игровой аккаунт не найден.')
        return account.id

    async def current(self, *, chat_id: int, mode: str, lock: bool = False):
        if lock:
            # A row does not exist for the first join, so lock the logical game
            # key before checking/inserting. This prevents two current games.
            await self.session.execute(
                text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                {'key': f'game:{mode}:room:{telegram_room_id(chat_id)}'},
            )
        statement = select(Game).where(
            Game.chat_id == chat_id, Game.mode == mode, Game.is_current.is_(True)
        )
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(statement)

    async def current_in_room(self, *, room_id: str, mode: str, lock: bool = False):
        """Find the current game by its platform room, independent of transport."""
        if lock:
            await self.session.execute(
                text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                {'key': f'game:{mode}:room:{room_id}'},
            )
        statement = select(Game).where(
            Game.room_id == room_id, Game.mode == mode, Game.is_current.is_(True)
        )
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(statement)

    async def ensure_telegram_room(self, chat_id: int) -> Room:
        """Idempotently materialize the transport room for legacy/dev schemas."""
        chat = await self.session.get(Chat, chat_id)
        if chat is None:
            raise LookupError('Чат игры не найден.')
        room_id = telegram_room_id(chat_id)
        statement = insert(Room).values(
            id=room_id, kind='telegram', title=chat.title or '', state={},
            owner_account_id=None,
        ).on_conflict_do_nothing(index_elements=[Room.id])
        await self.session.execute(statement)
        room = await self.session.scalar(select(Room).where(Room.id == room_id).with_for_update())
        if room is None or room.kind != 'telegram':
            raise RuntimeError('Некорректная привязка Telegram-комнаты.')
        statement = insert(RoomTransport).values(
            room_id=room_id, kind='telegram', external_id=str(chat_id),
            metadata_json={'chat_type': chat.type, 'username': chat.username},
        ).on_conflict_do_nothing(constraint='uq_room_transport_external')
        await self.session.execute(statement)
        transport = await self.session.scalar(select(RoomTransport).where(
            RoomTransport.kind == 'telegram', RoomTransport.external_id == str(chat_id)
        ))
        if transport is None or transport.room_id != room_id:
            raise RuntimeError('Telegram-чат связан с другой комнатой.')
        return room

    async def create_current(
        self, *, chat_id: int, mode: str, state: dict,
        status: str | None = None, phase: str | None = None,
        deadlines: dict[str, object] | None = None,
    ) -> Game:
        # Callers sometimes translate domain failures into HTTP responses
        # inside their outer transaction. Keep the repository operation
        # atomic even when that exception is caught by an adapter.
        async with self.session.begin_nested():
            status = str(status or state.get('status') or 'lobby')
            phase = str(phase or state.get('phase') or status)
            room = await self.ensure_telegram_room(chat_id)
            row = Game(
                id=str(uuid4()), chat_id=chat_id, room_id=room.id,
                mode=mode, status=status, phase=phase,
                revision=int(state.get('revision') or 0), state=state, is_current=True,
                started_at=datetime.now(timezone.utc) if status != 'lobby' else None,
                ended_at=datetime.now(timezone.utc) if status == 'finished' else None,
            )
            self.session.add(row)
            await self.session.flush()
            await self.sync_state(
                row, state, event_kind='game_created', status=status,
                phase=phase, deadlines=deadlines,
            )
        return row

    async def create_room_current(
        self, *, room_id: str, mode: str, state: dict,
        status: str | None = None, phase: str | None = None,
        deadlines: dict[str, object] | None = None,
        actor_account_id=None,
    ) -> Game:
        """Create a standalone-room game, without inventing Telegram identity.

        Callers still authorize the account through RoomMembership. This lower
        layer owns the unique-room lock and refuses Telegram transport rooms.
        """
        async with self.session.begin_nested():
            existing = await self.current_in_room(room_id=room_id, mode=mode, lock=True)
            if existing is not None:
                raise ValueError('В этой комнате уже есть текущая игра.')
            room = await self.session.scalar(select(Room).where(
                Room.id == room_id, Room.kind == 'standalone',
            ).with_for_update())
            if room is None:
                raise LookupError('Игровая комната не найдена.')
            status = str(status or state.get('status') or 'lobby')
            phase = str(phase or state.get('phase') or status)
            row = Game(
                id=str(uuid4()), room_id=room.id, chat_id=None, mode=mode,
                status=status, phase=phase,
                revision=int(state.get('revision') or 0), state=state, is_current=True,
                started_at=datetime.now(timezone.utc) if status != 'lobby' else None,
                ended_at=datetime.now(timezone.utc) if status == 'finished' else None,
            )
            self.session.add(row)
            await self.session.flush()
            await self.sync_state(
                row, state, event_kind='game_created', status=status,
                phase=phase, deadlines=deadlines,
                actor_account_id=actor_account_id,
            )
        return row

    async def replace_current(
        self, current: Game, *, state: dict,
        status: str | None = None, phase: str | None = None,
        deadlines: dict[str, object] | None = None,
    ) -> Game:
        # Reacquire the canonical room key before retiring the current row.
        # Adapter-level locks are still useful around the whole command, but
        # this repository primitive must remain safe when called independently.
        async with self.session.begin_nested():
            if current.chat_id is None:
                locked = await self.current_in_room(
                    room_id=current.room_id, mode=current.mode, lock=True
                )
            else:
                locked = await self.current(
                    chat_id=current.chat_id, mode=current.mode, lock=True
                )
            if locked is None or locked.id != current.id:
                raise RuntimeError('Текущая игра уже изменилась.')
            current = locked
            current.is_current = False
            current.ended_at = current.ended_at or datetime.now(timezone.utc)
            await self.session.flush()
            if current.chat_id is None:
                return await self.create_room_current(
                    room_id=current.room_id, mode=current.mode, state=state,
                    status=status, phase=phase, deadlines=deadlines,
                )
            return await self.create_current(
                chat_id=current.chat_id, mode=current.mode, state=state,
                status=status, phase=phase, deadlines=deadlines,
            )

    async def sync_state(
        self, row: Game, state: dict, *, event_kind: str,
        actor_user_id: int | None = None,
        actor_account_id=None,
        status: str | None = None,
        phase: str | None = None,
        deadlines: dict[str, object] | None = None,
    ) -> None:
        """Atomically update the envelope and every durable game projection."""
        async with self.session.begin_nested():
            await self._sync_state(
                row, state, event_kind=event_kind,
                actor_user_id=actor_user_id, actor_account_id=actor_account_id,
                status=status, phase=phase, deadlines=deadlines,
            )

    async def _sync_state(
        self, row: Game, state: dict, *, event_kind: str,
        actor_user_id: int | None = None,
        actor_account_id=None,
        status: str | None = None,
        phase: str | None = None,
        deadlines: dict[str, object] | None = None,
    ) -> None:
        previous_status = row.status
        status = str(status or state.get('status') or row.status or 'lobby')
        phase = str(phase or state.get('phase') or status)
        row.state = state
        row.status = status
        row.phase = phase
        row.revision = int(state.get('revision') or 0)
        if previous_status == 'lobby' and status != 'lobby' and row.started_at is None:
            row.started_at = datetime.now(timezone.utc)
        if status == 'finished' and row.ended_at is None:
            row.ended_at = datetime.now(timezone.utc)

        if row.mode == 'mafia':
            await self._sync_mafia_players(row, state, actor_user_id=actor_user_id,
                                           actor_account_id=actor_account_id)

        if deadlines is None:
            due_at = state.get('phase_deadline')
            deadlines = {'phase': due_at} if _deadline(due_at) is not None else {}
        await self.sync_deadlines(row, deadlines)

        next_index = int(await self.session.scalar(
            select(func.coalesce(func.max(GameEvent.event_index), 0)).where(
                GameEvent.game_id == row.id
            )
        ) or 0) + 1
        self.session.add(GameEvent(
            game_id=row.id, event_index=next_index, kind=event_kind,
            visibility='private' if event_kind == 'night_action' else 'public',
            actor_user_id=actor_user_id,
            actor_account_id=await self._resolve_actor_account(
                actor_user_id=actor_user_id, actor_account_id=actor_account_id,
            ),
            payload={'revision': row.revision, 'status': status},
        ))
        await self.session.flush()

    async def append_event(
        self, row: Game, *, kind: str, actor_user_id: int | None,
        visibility: str, payload: dict, actor_account_id=None,
    ) -> GameEvent:
        """Append a non-state-changing event while the caller holds the game lock."""
        if visibility not in {'public', 'private'}:
            raise ValueError('Invalid game event visibility')
        next_index = int(await self.session.scalar(
            select(func.coalesce(func.max(GameEvent.event_index), 0)).where(
                GameEvent.game_id == row.id
            )
        ) or 0) + 1
        event = GameEvent(
            game_id=row.id, event_index=next_index, kind=kind,
            visibility=visibility, actor_user_id=actor_user_id,
            actor_account_id=await self._resolve_actor_account(
                actor_user_id=actor_user_id, actor_account_id=actor_account_id,
            ), payload=payload,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def interrupt(
        self, row: Game, *, event_kind: str = 'game_interrupted',
        actor_user_id: int | None = None,
        actor_account_id=None,
    ) -> None:
        """End a current game without forcing a mode-specific transition.

        Moderation and maintenance are platform concerns.  They invalidate the
        current envelope atomically, preserve the last mode state for history,
        and make room for a fresh game after access is restored.
        """
        if not row.is_current or row.status in {'finished', 'stopped', 'interrupted'}:
            return
        state = deepcopy(row.state or {})
        revision = max(int(row.revision or 0), int(state.get('revision') or 0)) + 1
        state.update(status='interrupted', phase='interrupted', revision=revision)
        row.state = state
        row.status = 'interrupted'
        row.phase = 'interrupted'
        row.revision = revision
        row.is_current = False
        row.ended_at = datetime.now(timezone.utc)
        await self.sync_deadlines(row, {})
        next_index = int(await self.session.scalar(
            select(func.coalesce(func.max(GameEvent.event_index), 0)).where(
                GameEvent.game_id == row.id
            )
        ) or 0) + 1
        self.session.add(GameEvent(
            game_id=row.id, event_index=next_index, kind=event_kind,
            visibility='public', actor_user_id=actor_user_id,
            actor_account_id=await self._resolve_actor_account(
                actor_user_id=actor_user_id, actor_account_id=actor_account_id,
            ),
            payload={'revision': revision, 'status': 'interrupted'},
        ))
        await self.session.flush()

    async def _sync_mafia_players(
        self, row: Game, state: dict, *, actor_user_id: int | None = None,
        actor_account_id=None,
    ) -> None:
        """Materialize Mafia's private/public player projection outside the generic envelope."""

        from domain.mafia_state import canonicalize_mafia_state
        raw_players = state.get('players') if isinstance(state, dict) else None
        if isinstance(raw_players, list):
            raw_accounts = [player.get('account_id') for player in raw_players
                            if isinstance(player, dict) and player.get('account_id') is not None]
            for index, account_id in enumerate(raw_accounts):
                if any(account_id == prior for prior in raw_accounts[:index]):
                    raise ValueError('Duplicate account identity in Mafia state')
        state = canonicalize_mafia_state(state, row.room_id)
        row.state = state

        players = state.get('players') if isinstance(state.get('players'), list) else []
        assignments = state.get('assignments') if isinstance(state.get('assignments'), dict) else {}
        alive = set(state.get('alive') or [])
        present_accounts = []
        seen_accounts = set()
        for index, player in enumerate(players, 1):
            if not isinstance(player, dict):
                raise ValueError('Invalid Mafia player projection')
            raw_account_id = player.get('account_id')
            try:
                account_id = UUID(str(raw_account_id))
            except (TypeError, ValueError, AttributeError):
                raise ValueError('Invalid Mafia account identity') from None
            if await self.session.get(Account, account_id) is None:
                raise LookupError('Игровой аккаунт не найден.')

            if account_id in seen_accounts:
                raise ValueError('Duplicate account identity in Mafia state')
            seen_accounts.add(account_id)

            existing = await self.session.scalar(select(GamePlayer).where(
                GamePlayer.game_id == row.id,
                GamePlayer.account_id == account_id,
            ).with_for_update())
            existing_user_id = existing.user_id if existing is not None else None
            mapped_user_ids = list((await self.session.scalars(
                select(User.id)
                .join(AccountIdentity, AccountIdentity.provider_subject == cast(User.id, String))
                .where(
                    User.account_id == account_id,
                    AccountIdentity.account_id == account_id,
                    AccountIdentity.provider == 'telegram',
                    AccountIdentity.revoked_at.is_(None),
                    AccountIdentity.verified_at.is_not(None),
                )
            )).all())
            mapped_user_id = None
            try:
                normalized_actor_account_id = (
                    UUID(str(actor_account_id)) if actor_account_id is not None else None
                )
            except (TypeError, ValueError, AttributeError):
                raise ValueError('Некорректный аккаунт участника Mafia.') from None
            if actor_user_id is not None and normalized_actor_account_id == account_id:
                if actor_user_id not in mapped_user_ids:
                    raise RuntimeError('Telegram identity не соответствует аккаунту игрока.')
                mapped_user_id = actor_user_id
            elif existing_user_id in mapped_user_ids:
                mapped_user_id = existing_user_id
            elif len(mapped_user_ids) == 1:
                mapped_user_id = mapped_user_ids[0]
            if (existing_user_id is not None and mapped_user_id is not None
                    and existing_user_id != mapped_user_id):
                raise RuntimeError(
                    'Нельзя молча заменить Telegram identity существующего игрока.'
                )
            present_accounts.append(account_id)
            actor_key = str(account_id)
            assignment = assignments.get(actor_key)
            is_alive = not alive or actor_key in alive
            values = {
                'game_id': row.id,
                'account_id': account_id,
                # Transport identity is only a projection of the verified
                # account link; it never enters canonical game state.
                'user_id': mapped_user_id,
                'seat': f'p{index}',
                'status': 'active' if is_alive else 'eliminated',
                'public_state': {
                    'name': str(player.get('name') or '')[:120],
                    'ready': bool(player.get('ready')),
                },
                'private_state': (
                    {'role': assignment} if assignment is not None else {}
                ),
            }
            statement = insert(GamePlayer).values(**values)
            await self.session.execute(statement.on_conflict_do_update(
                index_elements=[GamePlayer.game_id, GamePlayer.account_id],
                set_={key: getattr(statement.excluded, key)
                      for key in ('user_id', 'seat', 'status', 'public_state', 'private_state')},
            ))
        if present_accounts:
            await self.session.execute(delete(GamePlayer).where(
                GamePlayer.game_id == row.id,
                GamePlayer.account_id.not_in(present_accounts),
            ))
        else:
            await self.session.execute(delete(GamePlayer).where(GamePlayer.game_id == row.id))

    @staticmethod
    def _deadline_id(game_id: str, kind: str) -> str:
        value = f'{game_id}:{kind}'
        if len(value) <= 96:
            return value
        return f'{game_id}:{sha256(kind.encode()).hexdigest()[:24]}'

    async def sync_deadlines(self, row: Game, deadlines: dict[str, object]) -> None:
        """Replace the pending deadline projection for one state revision."""

        if not isinstance(deadlines, dict) or any(
            not isinstance(kind, str) or not kind or len(kind) > 64
            for kind in deadlines
        ):
            raise ValueError('Invalid game deadlines')
        prepared = {
            kind: converted
            for kind, value in deadlines.items()
            if (converted := _deadline(value)) is not None
        }
        pending = update(GameDeadline).where(
            GameDeadline.game_id == row.id,
            GameDeadline.status == 'pending',
        )
        if prepared:
            pending = pending.where(GameDeadline.kind.not_in(prepared))
        await self.session.execute(pending.values(status='completed', completed_at=func.now()))
        for kind, due_at in prepared.items():
            statement = insert(GameDeadline).values(
                id=self._deadline_id(row.id, kind), game_id=row.id, kind=kind,
                due_at=due_at, status='pending', revision=row.revision,
            )
            await self.session.execute(statement.on_conflict_do_update(
                constraint='uq_game_deadline_kind',
                set_={
                    'due_at': statement.excluded.due_at,
                    'status': 'pending',
                    'revision': statement.excluded.revision,
                    'claimed_by': None,
                    'claimed_at': None,
                    'completed_at': None,
                },
            ))

    async def due_chat_ids(self, *, mode: str, now=None) -> list[int]:
        current_time = now or datetime.now(timezone.utc)
        if type(current_time) in {int, float}:
            current_time = datetime.fromtimestamp(current_time, tz=timezone.utc)
        statement = (
            select(Game.chat_id)
            .join(GameDeadline, GameDeadline.game_id == Game.id)
            .where(
                Game.mode == mode,
                Game.is_current.is_(True),
                GameDeadline.kind == 'phase',
                GameDeadline.status == 'pending',
                GameDeadline.due_at <= current_time,
            )
            .order_by(GameDeadline.due_at, Game.chat_id)
        )
        return list((await self.session.scalars(statement)).all())

    async def due_game_ids(self, *, mode: str, now=None) -> list[str]:
        """List due games without assuming that they have a Telegram transport."""
        current_time = now or datetime.now(timezone.utc)
        if type(current_time) in {int, float}:
            current_time = datetime.fromtimestamp(current_time, tz=timezone.utc)
        statement = (
            select(Game.id)
            .join(GameDeadline, GameDeadline.game_id == Game.id)
            .where(
                Game.mode == mode,
                Game.is_current.is_(True),
                GameDeadline.kind == 'phase',
                GameDeadline.status == 'pending',
                GameDeadline.due_at <= current_time,
            )
            .order_by(GameDeadline.due_at, Game.id)
        )
        return list((await self.session.scalars(statement)).all())

    async def reserve_command(
        self, *, command_id: str | None, game_id: str, actor_user_id: int | None = None,
        actor_account_id=None,
        kind: str, expected_revision: int | None, payload: dict,
    ) -> tuple[bool, dict | None]:
        """Reserve an adapter-neutral command or return its committed result."""
        if command_id is None:
            return False, None
        if not isinstance(command_id, str) or not 8 <= len(command_id) <= 64:
            raise ValueError('Некорректный идентификатор команды.')
        values = {
            'id': command_id,
            'game_id': game_id,
            'actor_user_id': actor_user_id,
            'actor_account_id': await self._resolve_actor_account(
                actor_user_id=actor_user_id, actor_account_id=actor_account_id,
            ),
            'kind': kind,
            'expected_revision': expected_revision,
            'payload': payload,
            'status': 'accepted',
        }
        statement = insert(GameCommand).values(**values).on_conflict_do_nothing(
            index_elements=[GameCommand.id]
        ).returning(GameCommand.id)
        if await self.session.scalar(statement):
            return False, None
        existing = await self.session.scalar(
            select(GameCommand).where(GameCommand.id == command_id).with_for_update()
        )
        if existing is None:
            raise RuntimeError('Не удалось проверить повтор команды.')
        if (
            existing.game_id != game_id
            or existing.actor_user_id != actor_user_id
            or existing.actor_account_id != values['actor_account_id']
            or existing.kind != kind
            or existing.expected_revision != expected_revision
            or existing.payload != payload
        ):
            raise RuntimeError('Идентификатор уже использован для другой команды или игры.')
        if existing.status != 'completed':
            raise RuntimeError('Команда ещё выполняется. Повторите позже.')
        return True, existing.result

    async def complete_command(self, command_id: str | None, result: dict) -> None:
        if command_id is None:
            return
        await self.session.execute(update(GameCommand).where(
            GameCommand.id == command_id, GameCommand.status == 'accepted'
        ).values(status='completed', result=result, processed_at=func.now()))
