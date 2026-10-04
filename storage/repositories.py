"""Repository operations shared by the bot, importer and future web API."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    AchievementGrant,
    Chat,
    ChatMember,
    DailySchedule,
    ImportRun,
    MessageCleanupItem,
    PhotoQuizItem,
    PollAnswer,
    QuizSession,
    SystemState,
    User,
)


class OperationalRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_chat(self, values: dict[str, Any]) -> None:
        statement = insert(Chat).values(**values)
        mutable = {key: getattr(statement.excluded, key) for key in values if key != "id"}
        await self.session.execute(statement.on_conflict_do_update(index_elements=[Chat.id], set_=mutable))

    async def ensure_chat(self, values: dict[str, Any]) -> None:
        await self.session.execute(
            insert(Chat).values(**values).on_conflict_do_nothing(index_elements=[Chat.id])
        )

    async def upsert_user(self, values: dict[str, Any]) -> None:
        statement = insert(User).values(**values)
        mutable = {key: getattr(statement.excluded, key) for key in values if key != "id"}
        await self.session.execute(statement.on_conflict_do_update(index_elements=[User.id], set_=mutable))

    async def ensure_user(self, values: dict[str, Any]) -> None:
        await self.session.execute(
            insert(User).values(**values).on_conflict_do_nothing(index_elements=[User.id])
        )

    async def upsert_member(self, values: dict[str, Any]) -> None:
        statement = insert(ChatMember).values(**values)
        mutable = {
            key: getattr(statement.excluded, key)
            for key in values
            if key not in {"chat_id", "user_id"}
        }
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=[ChatMember.chat_id, ChatMember.user_id], set_=mutable
            )
        )

    async def ensure_member(self, values: dict[str, Any]) -> None:
        await self.session.execute(
            insert(ChatMember)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[ChatMember.chat_id, ChatMember.user_id])
        )

    async def upsert_schedule(self, values: dict[str, Any]) -> None:
        statement = insert(DailySchedule).values(**values)
        mutable = {
            key: getattr(statement.excluded, key)
            for key in values
            if key not in {"id", "chat_id", "kind"}
        }
        await self.session.execute(
            statement.on_conflict_do_update(
                constraint="uq_daily_schedule_chat_kind", set_=mutable
            )
        )

    async def upsert_quiz_session(self, values: dict[str, Any]) -> None:
        statement = insert(QuizSession).values(**values)
        mutable = {key: getattr(statement.excluded, key) for key in values if key != "id"}
        await self.session.execute(
            statement.on_conflict_do_update(index_elements=[QuizSession.id], set_=mutable)
        )

    async def upsert_photo_item(self, values: dict[str, Any]) -> None:
        statement = insert(PhotoQuizItem).values(**values)
        mutable = {
            key: getattr(statement.excluded, key) for key in values if key != "media_key"
        }
        await self.session.execute(
            statement.on_conflict_do_update(index_elements=[PhotoQuizItem.media_key], set_=mutable)
        )

    async def upsert_system_state(self, key: str, payload: Any) -> None:
        statement = insert(SystemState).values(key=key, payload=payload)
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=[SystemState.key], set_={"payload": statement.excluded.payload}
            )
        )

    async def upsert_cleanup_item(self, values: dict[str, Any]) -> None:
        statement = insert(MessageCleanupItem).values(**values)
        mutable = {
            key: getattr(statement.excluded, key)
            for key in values
            if key not in {"chat_id", "message_id"}
        }
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=[MessageCleanupItem.chat_id, MessageCleanupItem.message_id],
                set_=mutable,
            )
        )

    async def grant_achievement(
        self,
        user_id: int,
        code: str,
        chat_id: int = 0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        statement = (
            insert(AchievementGrant)
            .values(
                user_id=user_id,
                chat_id=chat_id,
                code=code,
                metadata_json=metadata or {},
            )
            .on_conflict_do_nothing(constraint="uq_achievement_grant")
            .returning(AchievementGrant.id)
        )
        return (await self.session.scalar(statement)) is not None

    async def reserve_answer(
        self,
        *,
        poll_id: str,
        user_id: int,
        chat_id: int,
        points_delta: Decimal,
        selected_option: Optional[int],
        is_correct: Optional[bool],
        payload: Optional[dict[str, Any]] = None,
        game_id: Optional[str] = None,
        round_id: Optional[str] = None,
    ) -> bool:
        """Reserve an answer within the caller's scoring transaction."""
        answer_statement = (
            insert(PollAnswer)
            .values(
                poll_id=poll_id,
                user_id=user_id,
                chat_id=chat_id,
                points_delta=points_delta,
                selected_option=selected_option,
                is_correct=is_correct,
                payload=payload or {},
                game_id=game_id,
                round_id=round_id,
            )
            .on_conflict_do_nothing(index_elements=[PollAnswer.poll_id, PollAnswer.user_id])
            .returning(PollAnswer.poll_id)
        )
        return (await self.session.scalar(answer_statement)) is not None

    async def record_answer_and_add_score(
        self,
        *,
        poll_id: str,
        user_id: int,
        chat_id: int,
        points_delta: Decimal,
        selected_option: Optional[int],
        is_correct: Optional[bool],
        payload: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Atomically prevent duplicate scoring for one Telegram poll answer."""
        from .admin_actions import operation_fence, require_access
        await operation_fence(self.session)
        await require_access(self.session, chat_id, user_id)
        # All score writers lock the user before their chat membership.
        await self.session.scalar(select(User).where(User.id == user_id).with_for_update())
        if not await self.reserve_answer(
            poll_id=poll_id, user_id=user_id, chat_id=chat_id,
            points_delta=points_delta, selected_option=selected_option,
            is_correct=is_correct, payload=payload,
        ):
            return False

        counters: dict[Any, Any] = {
            ChatMember.score: ChatMember.score + points_delta,
            ChatMember.answered_count: ChatMember.answered_count + 1,
            ChatMember.last_answer_at: func.now(),
        }
        if is_correct:
            counters[ChatMember.correct_answers_count] = ChatMember.correct_answers_count + 1
            counters[ChatMember.consecutive_correct] = ChatMember.consecutive_correct + 1
            counters[ChatMember.max_consecutive_correct] = func.greatest(
                ChatMember.max_consecutive_correct, ChatMember.consecutive_correct + 1
            )
        elif is_correct is False:
            counters[ChatMember.consecutive_correct] = 0

        result = await self.session.execute(
            update(ChatMember)
            .where(ChatMember.chat_id == chat_id, ChatMember.user_id == user_id)
            .values(counters)
        )
        if result.rowcount != 1:
            raise LookupError(f"Chat member {chat_id}/{user_id} does not exist")

        user_result = await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                global_score=User.global_score + points_delta,
                total_answered=User.total_answered + 1,
                last_answer_at=func.now(),
            )
        )
        if user_result.rowcount != 1:
            raise LookupError(f"User {user_id} does not exist")
        return True

    async def get_chat_leaderboard(self, chat_id: int, limit: int = 20) -> list[ChatMember]:
        statement = (
            select(ChatMember)
            .where(ChatMember.chat_id == chat_id)
            .order_by(ChatMember.score.desc(), ChatMember.user_id)
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())

    async def add_achievement_codes(
        self, user_id: int, codes: Iterable[str], chat_id: int = 0
    ) -> int:
        added = 0
        for code in dict.fromkeys(str(item) for item in codes if item):
            added += int(await self.grant_achievement(user_id, code, chat_id))
        return added

    async def save_import_run(self, values: dict[str, Any]) -> None:
        statement = insert(ImportRun).values(**values)
        mutable = {key: getattr(statement.excluded, key) for key in values if key != "id"}
        await self.session.execute(
            statement.on_conflict_do_update(index_elements=[ImportRun.id], set_=mutable)
        )

    async def recompute_user_totals(self, user_id: int) -> None:
        aggregate = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(ChatMember.score), 0),
                    func.coalesce(func.sum(ChatMember.answered_count), 0),
                ).where(ChatMember.user_id == user_id)
            )
        ).one()
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(global_score=aggregate[0], total_answered=aggregate[1])
        )
