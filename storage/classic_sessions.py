"""Classic compatibility adapter backed exclusively by the shared games substrate.

The Telegram lifecycle still speaks the legacy snapshot shape while it is being
retired. This adapter deliberately stores that shape in ``games`` so there is
only one runtime source of truth during the controlled v2 cutover.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from sqlalchemy import select

from .admin_actions import operation_fence, require_access
from .cleanup import CleanupQueue
from .games import GameRepository
from .models import Game, PollAnswer, QuizSession, User
from .repositories import OperationalRepository


class ClassicSessionConflict(RuntimeError):
    pass


class ClassicSessions:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def key(chat_id):
        """Stable compatibility address, not the primary key of a games row."""
        return f"classic:{chat_id}"

    @staticmethod
    def _phase(state, status):
        if status != 'active':
            return 'finished'
        value = state.get('storage_phase')
        return value if value in {'active', 'sending', 'between'} else 'between'

    @staticmethod
    def _legacy_deadlines(state):
        result = {}
        polls = state.get('polls') if isinstance(state.get('polls'), dict) else {}
        for poll_id in state.get('active_poll_ids_in_session') or []:
            poll = polls.get(poll_id)
            deadline = poll.get('end_timestamp') if isinstance(poll, dict) else None
            if isinstance(poll_id, str) and type(deadline) in {int, float}:
                kind = 'legacy-close:' + sha256(poll_id.encode()).hexdigest()[:24]
                result[kind] = deadline
        next_at = state.get('next_question_at')
        if isinstance(next_at, str):
            try:
                result['legacy-advance'] = datetime.fromisoformat(next_at)
            except ValueError as exc:
                raise ClassicSessionConflict('Некорректный дедлайн викторины') from exc
        return result

    async def create(self, state):
        async with self.database.transaction() as session:
            await operation_fence(session)
            await require_access(session, state['chat_id'], state.get('created_by_user_id'))
            await OperationalRepository(session).ensure_chat(
                {'id': state['chat_id'], 'type': 'unknown'}
            )
            repo = GameRepository(session)
            existing = await repo.current(
                chat_id=state['chat_id'], mode='classic', lock=True
            )
            if existing is not None and existing.status == 'active':
                raise ClassicSessionConflict('В чате уже есть сохранённая викторина')
            value = deepcopy(state)
            value.update(storage_version=1, revision=1)
            kwargs = dict(
                state=value,
                status='active',
                phase=self._phase(value, 'active'),
                deadlines=self._legacy_deadlines(value),
            )
            if existing is None:
                await repo.create_current(
                    chat_id=state['chat_id'], mode='classic', **kwargs
                )
            else:
                await repo.replace_current(existing, **kwargs)
        return value

    async def save(self, state, *, status='active'):
        async with self.database.transaction() as session:
            await operation_fence(session)
            repo = GameRepository(session)
            row = await repo.current(
                chat_id=state['chat_id'], mode='classic', lock=True
            )
            if (
                row is None
                or row.status != 'active'
                or row.state.get('session_id') != state['session_id']
                or row.state.get('revision') != state['revision']
            ):
                raise ClassicSessionConflict(
                    'Викторина уже завершена, заменена или изменена'
                )
            value = deepcopy(state)
            value['revision'] += 1
            await repo.sync_state(
                row,
                value,
                event_kind='classic_checkpoint' if status == 'active' else f'classic_{status}',
                status=status,
                phase=self._phase(value, status),
                deadlines=self._legacy_deadlines(value) if status == 'active' else {},
            )
            if status == 'completed':
                from .category_statistics import record_completed_in
                await record_completed_in(session, value)
            if status != 'active':
                deadline = datetime.now(timezone.utc) + timedelta(seconds=180)
                ids = set(value.get('message_ids_to_delete', [])) | set(
                    value.get('results_message_ids', [])
                )
                for pair in value.get('poll_and_solution_message_ids', []):
                    ids.update(
                        item for item in (
                            pair.get('poll_msg_id'), pair.get('solution_msg_id')
                        ) if item
                    )
                for poll in value.get('polls', {}).values():
                    ids.update(
                        item for item in (
                            poll.get('message_id'),
                            poll.get('solution_placeholder_message_id'),
                            poll.get('solution_message_id'),
                        ) if item
                    )
                for message_id in ids:
                    await CleanupQueue.enqueue_in(
                        session, value['chat_id'], message_id, deadline,
                        source='classic',
                    )
        return value

    async def active(self):
        async with self.database.transaction() as session:
            rows = (await session.scalars(select(Game).where(
                Game.mode == 'classic',
                Game.status == 'active',
                Game.is_current.is_(True),
            ).order_by(Game.chat_id))).all()
            return [(self.key(row.chat_id), deepcopy(row.state)) for row in rows]

    async def legacy_active(self):
        """Defensive detector for rows that escaped the 0010 cutover."""
        async with self.database.transaction() as session:
            rows = (await session.scalars(select(QuizSession).where(
                QuizSession.kind != 'photo', QuizSession.status == 'active',
            ).order_by(QuizSession.id))).all()
            return [(row.id, deepcopy(row.state)) for row in rows]

    async def interrupt_legacy(self, key):
        """Only pre-cutover malformed rows may remain in quiz_sessions."""
        async with self.database.transaction() as session:
            row = await session.get(QuizSession, key, with_for_update=True)
            if row is not None and row.kind != 'photo' and row.status == 'active':
                row.status = 'interrupted'

    async def scores(self, chat_id, poll_ids):
        if not poll_ids:
            return {}
        async with self.database.transaction() as session:
            rows = (await session.execute(
                select(PollAnswer, User.display_name)
                .join(User, User.id == PollAnswer.user_id)
                .where(
                    PollAnswer.chat_id == chat_id,
                    PollAnswer.poll_id.in_(poll_ids),
                )
            )).all()
        result = {}
        for answer, name in rows:
            score = result.setdefault(
                str(answer.user_id),
                {
                    'name': name,
                    'score': 0,
                    'correct_count': 0,
                    'answered_this_session': set(),
                },
            )
            score['score'] += float(answer.points_delta)
            score['correct_count'] += int(bool(answer.is_correct))
            score['answered_this_session'].add(answer.poll_id)
        return result
