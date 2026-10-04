"""Transport-independent classic quiz lifecycle and compatibility projection."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Sequence

from sqlalchemy import func, select

from domain.classic import (
    advance_classic,
    classic_deadlines,
    close_round,
    finish_classic,
    normalize_classic,
    on_answer_applied,
    prepare_classic,
    project_classic,
    public_question,
    schedule_classic,
    start_classic,
    validate_classic_answer,
)
from domain.scoring import ClassicScoringRules, apply_classic_score
from storage.admin_actions import operation_fence, require_access
from storage.classic_sessions import ClassicSessionConflict
from storage.category_statistics import record_completed_in
from storage.games import GameRepository
from storage.members import MemberService
from storage.models import Game, GameDeadline, PollAnswer, QuizSession, User
from storage.notifications import NotificationQueue
from storage.repositories import OperationalRepository


def _questions_digest(questions: Sequence[dict[str, Any]]) -> str:
    raw = json.dumps(questions, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return sha256(raw.encode()).hexdigest()


class ClassicApplicationService:
    """Run all v2 Classic commands inside an adapter-owned transaction.

    The legacy projection remains readable while already-running v1 Telegram
    games drain. Every newly-created v2 game is authoritative in ``games``.
    """

    def __init__(self, database, session, *, rules: ClassicScoringRules | None = None):
        self.database = database
        self.session = session
        self.rules = rules
        self.games = GameRepository(session)

    async def _active(self, chat_id: int, *, lock: bool = False):
        return await self.games.current(chat_id=chat_id, mode='classic', lock=lock)

    @staticmethod
    def _current_poll(state: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        """Compatibility reader for v1 sessions only."""
        polls = state.get('polls')
        if not isinstance(polls, dict):
            return None
        candidates = []
        latest = state.get('latest_poll_id_sent')
        if isinstance(latest, str):
            candidates.append(latest)
        active = state.get('active_poll_ids_in_session')
        if isinstance(active, (list, tuple, set)):
            candidates.extend(reversed(list(active)))
        for poll_id in candidates:
            poll = polls.get(poll_id)
            if isinstance(poll_id, str) and isinstance(poll, dict):
                return poll_id, poll
        return None

    async def _answers(self, game_id: str, user_id: int) -> dict[str, int]:
        rows = (await self.session.scalars(select(PollAnswer).where(
            PollAnswer.game_id == game_id,
            PollAnswer.user_id == user_id,
        ))).all()
        return {
            row.round_id: row.selected_option
            for row in rows
            if isinstance(row.round_id, str) and type(row.selected_option) is int
        }

    async def _enqueue_question(self, game: Game, state: dict[str, Any]) -> None:
        round_id = state.get('current_round_id')
        if not isinstance(round_id, str):
            return
        await NotificationQueue.enqueue_in(
            self.session,
            kind='classic.question',
            dedupe_key=f'classic:{game.id}:question:{round_id}',
            payload={'round_id': round_id, 'revision': state['revision']},
            game_id=game.id,
            chat_id=game.chat_id,
        )

    async def _enqueue_finished(self, game: Game, state: dict[str, Any]) -> None:
        await NotificationQueue.enqueue_in(
            self.session,
            kind='classic.finished',
            dedupe_key=f'classic:{game.id}:finished',
            payload={
                'revision': state['revision'],
                'reason': state.get('finish_reason') or 'completed',
            },
            game_id=game.id,
            chat_id=game.chat_id,
        )

    async def current(self, *, chat_id: int, user_id: int) -> dict[str, Any] | None:
        game = await self._active(chat_id)
        if game is None or game.status != 'active' or not isinstance(game.state, dict):
            return None
        state = normalize_classic(game.state, chat_id=chat_id)
        if state is not None:
            answers = await self._answers(game.id, user_id)
            result = project_classic(
                state, selected_options=answers
            )
            if result['question'] and result['question']['answered']:
                answer = await self.session.get(
                    PollAnswer, (result['question']['round_id'], user_id)
                )
                if answer is not None:
                    result['question']['points'] = str(answer.points_delta)
            result['game_id'] = game.id
            return result

        # A migrated v1 game remains playable only through its compatibility
        # adapter; Mini App can still project and answer the same durable poll.
        current = self._current_poll(game.state)
        if current is None:
            return {'phase': game.state.get('storage_phase', 'between'), 'question': None}
        poll_id, poll = current
        answer = await self.session.get(PollAnswer, (poll_id, user_id))
        selected = answer.selected_option if answer is not None else None
        try:
            question = public_question(poll_id, poll, selected_option=selected)
        except ValueError:
            return {'phase': 'upgrade-required', 'question': None}
        if answer is not None:
            question['points'] = str(answer.points_delta)
        return {
            'game_id': game.id,
            'revision': game.revision,
            'phase': 'active' if not question['closed'] else 'between',
            'question': question,
            'game': {
                'current': max(0, int(game.state.get('current_question_index') or 0)),
                'total': max(0, int(game.state.get('num_questions_to_ask') or 0)),
            },
        }

    async def start(
        self,
        *,
        chat_id: int,
        user_id: int | None,
        display_name: str | None,
        questions: Sequence[dict[str, Any]],
        quiz_type: str = 'session',
        open_seconds: int = 30,
        interval_seconds: int = 0,
        command_id: str | None = None,
        start_delay_seconds: int = 0,
        now=None,
    ) -> dict[str, Any]:
        await operation_fence(self.session)
        await require_access(self.session, chat_id, user_id)
        operational = OperationalRepository(self.session)
        await operational.ensure_chat({'id': chat_id, 'type': 'unknown'})
        if user_id is not None:
            await operational.ensure_user({'id': user_id, 'display_name': display_name or f'User {user_id}'})
            await operational.ensure_member({'chat_id': chat_id, 'user_id': user_id})
        current = await self._active(chat_id, lock=True)
        payload = {
            'quiz_type': quiz_type,
            'open_seconds': open_seconds,
            'interval_seconds': interval_seconds,
            'question_count': len(questions),
            'questions_digest': _questions_digest(questions),
            'start_delay_seconds': start_delay_seconds,
        }
        if current is not None and current.status == 'active':
            cached, result = await self.games.reserve_command(
                command_id=command_id, game_id=current.id,
                actor_user_id=user_id, kind='classic.start',
                expected_revision=None, payload=payload,
            )
            if cached:
                return result
            raise ClassicSessionConflict('В чате уже идёт викторина.')
        state = prepare_classic(
            chat_id=chat_id,
            creator_id=user_id,
            questions=questions,
            quiz_type=quiz_type,
            open_seconds=open_seconds,
            interval_seconds=interval_seconds,
        )
        if type(start_delay_seconds) is not int or not 0 <= start_delay_seconds <= 3600:
            raise ValueError('Задержка старта должна быть от 0 до 3600 секунд.')
        timestamp = (
            now.timestamp() if isinstance(now, datetime)
            else float(now) if type(now) in {int, float}
            else datetime.now(timezone.utc).timestamp()
        )
        state = (
            schedule_classic(
                state, expected_revision=0,
                start_at=timestamp + start_delay_seconds,
            )
            if start_delay_seconds else
            start_classic(state, expected_revision=0, now=timestamp)
        )
        kwargs = dict(
            state=state,
            status='active',
            phase=state['phase'],
            deadlines=classic_deadlines(state),
        )
        if current is None:
            game = await self.games.create_current(
                chat_id=chat_id, mode='classic', **kwargs
            )
        else:
            game = await self.games.replace_current(current, **kwargs)
        if state['status'] == 'active':
            await self._enqueue_question(game, state)
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=game.id,
            actor_user_id=user_id, kind='classic.start',
            expected_revision=None, payload=payload,
        )
        if cached:
            return result
        result = project_classic(state, now=now)
        result['game_id'] = game.id
        await self.games.complete_command(command_id, result)
        return result

    async def answer(
        self,
        *,
        chat_id: int,
        user_id: int,
        display_name: str,
        poll_id: str | None = None,
        round_id: str | None = None,
        selected_option: int,
        command_id: str | None = None,
        expected_revision: int | None = None,
        now=None,
    ) -> dict[str, Any]:
        await operation_fence(self.session)
        await require_access(self.session, chat_id, user_id)
        operational = OperationalRepository(self.session)
        await operational.ensure_chat({'id': chat_id, 'type': 'unknown'})
        await operational.ensure_user({'id': user_id, 'display_name': display_name})
        await operational.ensure_member({'chat_id': chat_id, 'user_id': user_id})
        game = await self._active(chat_id, lock=True)
        if game is None or game.status != 'active' or not isinstance(game.state, dict):
            raise LookupError('Активная викторина не найдена')
        state = normalize_classic(game.state, chat_id=chat_id)
        if state is not None:
            if self.rules is None:
                raise RuntimeError('Правила подсчёта Classic не настроены.')
            internal_id = round_id or poll_id
            if not isinstance(internal_id, str):
                raise ValueError('Не указан вопрос.')
            payload = {'round_id': internal_id, 'selected_option': selected_option}
            cached, result = await self.games.reserve_command(
                command_id=command_id, game_id=game.id,
                actor_user_id=user_id, kind='classic.answer',
                expected_revision=expected_revision, payload=payload,
            )
            if cached:
                return result
            item = validate_classic_answer(
                state, round_id=internal_id,
                selected_option=selected_option, now=now,
            )
            transition_result = None

            async def transition(data):
                nonlocal transition_result
                transition_result = apply_classic_score(
                    data,
                    chat_id=chat_id,
                    user_id=user_id,
                    display_name=display_name,
                    answer_id=internal_id,
                    is_correct=selected_option == item['correct_option_index'],
                    rules=self.rules,
                )
                return transition_result

            score = await MemberService(self.database).apply_answer(
                chat_id=chat_id,
                user_id=user_id,
                display_name=display_name,
                answer_id=internal_id,
                is_correct=selected_option == item['correct_option_index'],
                selected_option=selected_option,
                transition=transition,
                transaction_session=self.session,
                classic_game_id=game.id,
                classic_round_id=internal_id,
            )
            if score.applied:
                next_state = on_answer_applied(state, round_id=internal_id, now=now)
                if next_state != game.state:
                    await self.games.sync_state(
                        game, next_state, event_kind='classic_answered',
                        actor_user_id=user_id, status=next_state['status'],
                        phase=next_state['phase'],
                        deadlines=classic_deadlines(next_state),
                    )
                state = next_state
            answers = await self._answers(game.id, user_id)
            projection = project_classic(
                state, selected_options=answers, now=now
            )
            saved = await self.session.get(PollAnswer, (internal_id, user_id))
            result = {
                **projection,
                'applied': score.applied,
                'own_score': str(score.data.get('score', 0)),
                'points': str(saved.points_delta if saved is not None else 0),
            }
            if result['question'] is not None and saved is not None:
                result['question']['points'] = str(saved.points_delta)
            await self.games.complete_command(command_id, result)
            return result

        # Compatibility path for a migrated Telegram v1 session.
        if self.rules is None:
            raise RuntimeError('Правила подсчёта Classic не настроены.')
        legacy_id = poll_id or round_id
        current = self._current_poll(game.state)
        if current is None or current[0] != legacy_id:
            raise ClassicSessionConflict('Вопрос уже сменился')
        poll = current[1]
        options = poll.get('options')
        correct = poll.get('correct_option_index')
        if (
            type(selected_option) is not int
            or not isinstance(options, list)
            or not 0 <= selected_option < len(options)
            or type(correct) is not int
            or not 0 <= correct < len(options)
        ):
            raise ValueError('Некорректный вариант ответа')
        deadline = poll.get('end_timestamp')
        if (
            not isinstance(deadline, (int, float))
            or datetime.now(timezone.utc).timestamp() > deadline
        ):
            raise ClassicSessionConflict('Время ответа истекло')
        transition_result = None

        async def transition(data):
            nonlocal transition_result
            transition_result = apply_classic_score(
                data,
                chat_id=chat_id,
                user_id=user_id,
                display_name=display_name,
                answer_id=legacy_id,
                is_correct=selected_option == correct,
                rules=self.rules,
            )
            return transition_result

        score = await MemberService(self.database).apply_answer(
            chat_id=chat_id,
            user_id=user_id,
            display_name=display_name,
            answer_id=legacy_id,
            is_correct=selected_option == correct,
            selected_option=selected_option,
            transition=transition,
            transaction_session=self.session,
            classic_session_id=game.state.get('session_id'),
        )
        saved = await self.session.get(PollAnswer, (legacy_id, user_id))
        original_selection = saved.selected_option if saved is not None else selected_option
        question = public_question(
            legacy_id, poll, selected_option=original_selection
        )
        return {
            'applied': score.applied,
            'question': question,
            'own_score': str(score.data.get('score', 0)),
            'points': str(saved.points_delta if saved is not None else 0),
        }

    async def advance(
        self, *, chat_id: int, round_id: str, cause: str,
        expected_revision: int, now=None,
    ) -> dict[str, Any]:
        game = await self._active(chat_id, lock=True)
        state = normalize_classic(game.state, chat_id=chat_id) if game else None
        if game is None or state is None:
            raise LookupError('Активная викторина не найдена.')
        state = advance_classic(
            state, round_id=round_id, cause=cause,
            expected_revision=expected_revision, now=now,
        )
        await self.games.sync_state(
            game, state, event_kind='classic_round_opened',
            status=state['status'], phase=state['phase'],
            deadlines=classic_deadlines(state),
        )
        await self._enqueue_question(game, state)
        result = project_classic(state, now=now)
        result['game_id'] = game.id
        return result

    async def close(self, *, chat_id: int, round_id: str, now=None) -> dict[str, Any]:
        game = await self._active(chat_id, lock=True)
        state = normalize_classic(game.state, chat_id=chat_id) if game else None
        if game is None or state is None:
            raise LookupError('Активная викторина не найдена.')
        was_finished = state['status'] == 'finished'
        state = close_round(state, round_id=round_id, now=now)
        if not was_finished and state['status'] == 'finished':
            await record_completed_in(self.session, state)
        await self.games.sync_state(
            game, state, event_kind='classic_round_closed',
            status=state['status'], phase=state['phase'],
            deadlines=classic_deadlines(state),
        )
        if not was_finished and state['status'] == 'finished':
            await self._enqueue_finished(game, state)
        result = project_classic(state, now=now)
        result['game_id'] = game.id
        return result

    async def stop(
        self, *, chat_id: int, user_id: int, expected_revision: int,
        command_id: str | None = None, now=None, allow_admin: bool = False,
    ) -> dict[str, Any]:
        await operation_fence(self.session)
        await require_access(self.session, chat_id, user_id)
        game = await self._active(chat_id, lock=True)
        state = normalize_classic(game.state, chat_id=chat_id) if game else None
        if game is None or state is None:
            raise LookupError('Активная викторина не найдена.')
        if state.get('creator_id') != user_id and not allow_admin:
            raise PermissionError('Остановить викторину может её создатель или администратор чата.')
        payload = {'reason': 'stopped'}
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=game.id,
            actor_user_id=user_id, kind='classic.stop',
            expected_revision=expected_revision, payload=payload,
        )
        if cached:
            return result
        state = finish_classic(
            state, reason='stopped', expected_revision=expected_revision, now=now
        )
        await self.games.sync_state(
            game, state, event_kind='classic_stopped', actor_user_id=user_id,
            status=state['status'], phase=state['phase'], deadlines={},
        )
        result = project_classic(state, now=now)
        result['game_id'] = game.id
        await self.games.complete_command(command_id, result)
        return result

    async def settle_due(
        self, *, chat_id: int, user_id: int | None = None, now=None,
    ) -> dict[str, Any] | None:
        """Apply every transition due at server time, then return the viewer projection."""
        await operation_fence(self.session)
        await require_access(self.session, chat_id, user_id)
        game = await self._active(chat_id, lock=True)
        state = normalize_classic(game.state, chat_id=chat_id) if game else None
        if game is None or game.status != 'active' or state is None:
            return None
        timestamp = (
            now.timestamp() if isinstance(now, datetime)
            else float(now) if type(now) in {int, float}
            else datetime.now(timezone.utc).timestamp()
        )
        changed = False
        was_finished = state['status'] == 'finished'
        previous_round_id = state['current_round_id']
        for _ in range(len(state['rounds']) * 3):
            due = sorted(
                (deadline, kind)
                for kind, deadline in classic_deadlines(state).items()
                if deadline <= timestamp
            )
            if not due:
                break
            _, kind = due[0]
            if kind == 'start':
                state = start_classic(
                    state, expected_revision=state['revision'], now=timestamp
                )
                changed = True
                continue
            action, internal_id = kind.split(':', 1)
            if action == 'advance':
                state = advance_classic(
                    state, round_id=internal_id, cause='answer',
                    expected_revision=state['revision'], now=timestamp,
                )
            else:
                item = next(
                    item for item in state['rounds']
                    if item['round_id'] == internal_id
                )
                if (
                    state['current_round_id'] == internal_id
                    and item['index'] + 1 < len(state['rounds'])
                ):
                    state = advance_classic(
                        state, round_id=internal_id, cause='deadline',
                        expected_revision=state['revision'], now=timestamp,
                    )
                else:
                    state = close_round(
                        state, round_id=internal_id, now=timestamp
                    )
            changed = True
        else:
            raise RuntimeError('Превышен предел переходов викторины.')
        if changed:
            if not was_finished and state['status'] == 'finished':
                await record_completed_in(self.session, state)
            await self.games.sync_state(
                game, state, event_kind='classic_deadline_advanced',
                status=state['status'], phase=state['phase'],
                deadlines=classic_deadlines(state),
            )
            if not was_finished and state['status'] == 'finished':
                await self._enqueue_finished(game, state)
            if state.get('current_round_id') != previous_round_id:
                await self._enqueue_question(game, state)
        result = project_classic(
            state,
            selected_options=await self._answers(game.id, user_id) if user_id is not None else {},
            now=timestamp,
        )
        result['game_id'] = game.id
        return result

    async def question_delivery(
        self, *, game_id: str, round_id: str,
    ) -> dict[str, Any] | None:
        """Private delivery effect; never expose this projection through HTTP."""
        game = await self.session.get(Game, game_id)
        state = normalize_classic(game.state, chat_id=game.chat_id) if game else None
        if game is None or not game.is_current or state is None:
            return None
        item = next(
            (item for item in state['rounds'] if item['round_id'] == round_id), None
        )
        if item is None or item['status'] != 'open':
            return None
        return {
            'game_id': game.id,
            'round_id': round_id,
            'chat_id': game.chat_id,
            'question': item['display_question'],
            'options': list(item['options']),
            'correct_option': item['correct_option_index'],
            'closes_at': item['closes_at'],
            'revision': state['revision'],
        }

    async def result_delivery(self, *, game_id: str) -> dict[str, Any] | None:
        """Private completion effect assembled from the authoritative ledger."""
        game = await self.session.get(Game, game_id)
        state = normalize_classic(game.state, chat_id=game.chat_id) if game else None
        if game is None or state is None or state['status'] != 'finished':
            return None
        rows = (await self.session.execute(
            select(
                PollAnswer.user_id,
                User.display_name,
                func.coalesce(func.sum(PollAnswer.points_delta), 0),
                func.count().filter(PollAnswer.is_correct.is_(True)),
            )
            .join(User, User.id == PollAnswer.user_id)
            .where(PollAnswer.game_id == game.id)
            .group_by(PollAnswer.user_id, User.display_name)
            .order_by(
                func.coalesce(func.sum(PollAnswer.points_delta), 0).desc(),
                PollAnswer.user_id,
            )
        )).all()
        return {
            'game_id': game.id,
            'chat_id': game.chat_id,
            'revision': state['revision'],
            'question_count': state['config']['question_count'],
            'players': [
                {
                    'user_id': user_id,
                    'name': name,
                    'points': str(points),
                    'correct': correct,
                }
                for user_id, name, points, correct in rows
            ],
        }

    async def due(self, *, now=None) -> list[tuple[int, str, str, int]]:
        """Return due v2 transitions; a worker still revalidates each under row lock."""
        moment = now or datetime.now(timezone.utc)
        if type(moment) in {int, float}:
            moment = datetime.fromtimestamp(moment, timezone.utc)
        rows = (await self.session.execute(
            select(Game.chat_id, GameDeadline.kind, GameDeadline.revision)
            .join(GameDeadline, GameDeadline.game_id == Game.id)
            .where(
                Game.mode == 'classic', Game.is_current.is_(True),
                Game.status == 'active', GameDeadline.status == 'pending',
                GameDeadline.due_at <= moment,
                (GameDeadline.kind == 'start')
                | GameDeadline.kind.like('close:%')
                | GameDeadline.kind.like('advance:%'),
            )
            .order_by(GameDeadline.due_at, Game.chat_id, GameDeadline.kind)
        )).all()
        return [
            (
                chat_id,
                kind.split(':', 1)[0],
                kind.split(':', 1)[1] if ':' in kind else '',
                revision,
            )
            for chat_id, kind, revision in rows
        ]
