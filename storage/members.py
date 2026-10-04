"""Transactional member commands shared by Telegram and the local admin API."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import nullcontext
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select, update

from .database import Database
from .models import ChatMember, Game, PollAnswer, User, QuizSession
from .repositories import OperationalRepository
from .runtime import member_data, member_values
from .admin_actions import operation_fence, require_access


class MemberNotFound(LookupError):
    pass


class ScoreConflict(ValueError):
    pass


@dataclass
class AnswerResult:
    applied: bool
    data: dict[str, Any]
    result: Any = None


class MemberService:
    def __init__(self, database: Database):
        self.database = database

    async def apply_answer(
        self, *, chat_id: int, user_id: int, display_name: str | None, answer_id: str,
        is_correct: bool, transition: Callable[[dict[str, Any]], Awaitable[Any]],
        kind: str = "classic", selected_option: int | None = None,
        transaction_session=None,
        classic_session_id: str | None = None,
        classic_game_id: str | None = None,
        classic_round_id: str | None = None,
        game_id: str | None = None,
        game_round_id: str | None = None,
    ) -> AnswerResult:
        """Compute from locked DB state, then persist ledger/profile/awards together.

        transition mutates a detached view and must not send messages or modify
        shared BotState. By default return means commit succeeded. A caller
        supplying transaction_session owns the commit (e.g. photo completion).
        """
        if kind not in {"classic", "photo"}:
            raise ValueError("Unsupported answer kind")
        async with (self.database.transaction() if transaction_session is None else nullcontext(transaction_session)) as session:
            if transaction_session is None:
                await operation_fence(session)
            await require_access(session, chat_id, user_id)
            if classic_session_id is not None:
                from .classic_sessions import ClassicSessionConflict
                quiz = await session.scalar(select(Game).where(
                    Game.chat_id == chat_id,
                    Game.mode == 'classic',
                    Game.is_current.is_(True),
                ).with_for_update())
                if quiz is None:  # Pre-0010 compatibility for isolated unit schemas.
                    quiz = await session.scalar(select(QuizSession).where(
                        QuizSession.id == f"classic:{chat_id}").with_for_update())
                poll = (quiz.state.get("polls", {}).get(answer_id) if quiz else None)
                if (quiz is None or quiz.status != "active" or quiz.state.get("session_id") != classic_session_id
                        or not poll or datetime.now(timezone.utc).timestamp() > poll["end_timestamp"]):
                    raise ClassicSessionConflict("Опрос завершён или его состояние не подтверждено")
            if classic_game_id is not None:
                from domain.classic import normalize_classic, validate_classic_answer
                game = await session.scalar(select(Game).where(
                    Game.id == classic_game_id,
                    Game.mode == 'classic',
                    Game.is_current.is_(True),
                ).with_for_update())
                state = normalize_classic(game.state, chat_id=chat_id) if game else None
                if (
                    game is None or game.status != 'active' or state is None
                    or classic_round_id != answer_id or selected_option is None
                ):
                    raise ValueError('Вопрос завершён или его состояние не подтверждено')
                try:
                    validate_classic_answer(
                        state, round_id=classic_round_id,
                        selected_option=selected_option,
                    )
                except (LookupError, RuntimeError, ValueError) as exc:
                    raise ValueError(str(exc)) from exc
            if game_id is not None:
                game = await session.scalar(select(Game).where(
                    Game.id == game_id,
                    Game.chat_id == chat_id,
                    Game.mode == kind,
                    Game.is_current.is_(True),
                ).with_for_update())
                if (
                    game is None or game.status != "active"
                    or not isinstance(game_round_id, str)
                    or game_round_id != answer_id
                    or (game.state or {}).get("current_round_id") != game_round_id
                ):
                    raise ValueError("Вопрос завершён или его состояние не подтверждено")
            repo = OperationalRepository(session)
            await repo.ensure_chat({"id": chat_id, "type": "unknown"})
            await repo.ensure_user({"id": user_id, "display_name": display_name or f"User {user_id}"})
            user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
            effective_name = display_name or user.display_name
            await repo.ensure_member({"chat_id": chat_id, "user_id": user_id})
            member = await session.scalar(select(ChatMember).where(
                ChatMember.chat_id == chat_id, ChatMember.user_id == user_id,
            ).with_for_update())
            data = member_data(member, user)
            if (
                await session.get(PollAnswer, (answer_id, user_id)) is not None
                or (kind == "classic" and answer_id in (
                    data["answered_polls"] | data["daily_answered_polls"]
                ))
            ):
                return AnswerResult(False, data)

            result = await transition(data)
            values = member_values(chat_id, user_id, data)
            # Legacy photo awards increase score/correct count, not classic poll count.
            values["answered_count"] = member.answered_count + (kind == "classic")
            delta = values["score"] - member.score
            if not await repo.reserve_answer(
                poll_id=answer_id, user_id=user_id, chat_id=chat_id,
                points_delta=delta, selected_option=selected_option,
                is_correct=is_correct, payload={"quiz_type": kind},
                game_id=game_id or classic_game_id,
                round_id=game_round_id or classic_round_id,
            ):
                return AnswerResult(False, member_data(member, user))
            await repo.upsert_member(values)
            await repo.add_achievement_codes(user_id, values["milestone_codes"])
            await repo.add_achievement_codes(user_id, values["streak_achievement_codes"])
            await session.execute(update(User).where(User.id == user_id).values(
                display_name=effective_name,
                global_score=User.global_score + delta,
                total_answered=User.total_answered + int(kind == "classic"),
                first_answer_at=user.first_answer_at or values["first_answer_at"],
                last_answer_at=values["last_answer_at"] or user.last_answer_at,
            ))
            data["score"] = float(values["score"])
            data["name"] = effective_name
            answer = AnswerResult(True, data, result)
        return answer

    async def set_score(
        self, chat_id: int, user_id: int, score: Decimal,
        expected_score: Decimal | None = None,
    ) -> Decimal:
        if not score.is_finite() or abs(score) > Decimal("99999999999.999"):
            raise ValueError("Score must be finite and fit Numeric(14,3)")
        if expected_score is not None and not expected_score.is_finite():
            raise ValueError("Expected score must be finite")
        score = score.quantize(Decimal("0.001"))
        async with self.database.transaction() as session:
            await operation_fence(session)
            user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
            member = await session.scalar(select(ChatMember).where(
                ChatMember.chat_id == chat_id, ChatMember.user_id == user_id,
            ).with_for_update())
            if user is None or member is None:
                raise MemberNotFound("Пользователь не найден в чате")
            old_score = member.score
            if expected_score is not None and old_score != expected_score:
                raise ScoreConflict("Баллы уже изменились. Обновите данные и повторите действие.")
            member.score = score
            user.global_score += score - old_score
            await session.flush()
        return old_score
