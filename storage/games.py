"""Persistence primitives for versioned, long-running game modes."""

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from .models import Game, GameCommand, GameDeadline, GameEvent, GamePlayer


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

    async def current(self, *, chat_id: int, mode: str, lock: bool = False):
        if lock:
            # A row does not exist for the first join, so lock the logical game
            # key before checking/inserting. This prevents two current games.
            await self.session.execute(
                text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                {'key': f'game:{mode}:{chat_id}'},
            )
        statement = select(Game).where(
            Game.chat_id == chat_id, Game.mode == mode, Game.is_current.is_(True)
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def create_current(
        self, *, chat_id: int, mode: str, state: dict,
        status: str | None = None, phase: str | None = None,
        deadlines: dict[str, object] | None = None,
    ) -> Game:
        status = str(status or state.get('status') or 'lobby')
        phase = str(phase or state.get('phase') or status)
        row = Game(
            id=str(uuid4()), chat_id=chat_id, mode=mode, status=status, phase=phase,
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

    async def replace_current(
        self, current: Game, *, state: dict,
        status: str | None = None, phase: str | None = None,
        deadlines: dict[str, object] | None = None,
    ) -> Game:
        current.is_current = False
        current.ended_at = current.ended_at or datetime.now(timezone.utc)
        await self.session.flush()
        return await self.create_current(
            chat_id=current.chat_id, mode=current.mode, state=state,
            status=status, phase=phase, deadlines=deadlines,
        )

    async def sync_state(
        self, row: Game, state: dict, *, event_kind: str,
        actor_user_id: int | None = None,
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
            await self._sync_mafia_players(row, state)

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
            payload={'revision': row.revision, 'status': status},
        ))
        await self.session.flush()

    async def interrupt(
        self, row: Game, *, event_kind: str = 'game_interrupted',
        actor_user_id: int | None = None,
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
            payload={'revision': revision, 'status': 'interrupted'},
        ))
        await self.session.flush()

    async def _sync_mafia_players(self, row: Game, state: dict) -> None:
        """Materialize Mafia's private/public player projection outside the generic envelope."""

        players = state.get('players') if isinstance(state.get('players'), list) else []
        assignments = state.get('assignments') if isinstance(state.get('assignments'), dict) else {}
        alive = set(state.get('alive') or [])
        present_ids = []
        for index, player in enumerate(players, 1):
            user_id = player['user_id']
            present_ids.append(user_id)
            values = {
                'game_id': row.id,
                'user_id': user_id,
                'seat': f'p{index}',
                'status': 'active' if not alive or user_id in alive else 'eliminated',
                'public_state': {
                    'name': str(player.get('name') or '')[:120],
                    'ready': bool(player.get('ready')),
                },
                'private_state': (
                    {'role': assignments[str(user_id)]}
                    if str(user_id) in assignments else {}
                ),
            }
            statement = insert(GamePlayer).values(**values)
            await self.session.execute(statement.on_conflict_do_update(
                index_elements=[GamePlayer.game_id, GamePlayer.user_id],
                set_={key: getattr(statement.excluded, key)
                      for key in ('seat', 'status', 'public_state', 'private_state')},
            ))
        if present_ids:
            await self.session.execute(delete(GamePlayer).where(
                GamePlayer.game_id == row.id, GamePlayer.user_id.not_in(present_ids)
            ))

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

    async def reserve_command(
        self, *, command_id: str | None, game_id: str, actor_user_id: int,
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
            existing.actor_user_id != actor_user_id
            or existing.kind != kind
            or existing.expected_revision != expected_revision
            or existing.payload != payload
        ):
            raise RuntimeError('Идентификатор уже использован для другой команды.')
        if existing.status != 'completed':
            raise RuntimeError('Команда ещё выполняется. Повторите позже.')
        return True, existing.result

    async def complete_command(self, command_id: str | None, result: dict) -> None:
        if command_id is None:
            return
        await self.session.execute(update(GameCommand).where(
            GameCommand.id == command_id, GameCommand.status == 'accepted'
        ).values(status='completed', result=result, processed_at=func.now()))
