import asyncio
import os
from decimal import Decimal
from types import SimpleNamespace

import pytest
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import delete, select
from telegram import User as TelegramUser

from modules.score_manager import ScoreManager
from state import BotState
from storage.database import Database, DatabaseSettings, normalize_database_url
from storage.models import (
    AchievementGrant,
    Chat,
    ChatMember,
    DailySchedule,
    Game,
    MessageCleanupItem,
    PollAnswer,
    QuizSession,
    User,
)
from storage.repositories import OperationalRepository
from storage.runtime import PostgresRuntimeStorage


TEST_CHAT_ID = -900000000001
TEST_USER_ID = 900000000001
TEST_POLL_ID = "storage-integration-idempotency"
TEST_SCORE_MANAGER_POLL_ID = "score-manager-idempotency"


def test_duplicate_poll_answer_is_scored_once() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    asyncio.run(_exercise_duplicate_answer(normalize_database_url(database_url)))


def test_runtime_state_round_trip() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    asyncio.run(_exercise_runtime_round_trip(normalize_database_url(database_url)))


def test_score_manager_uses_postgres_as_idempotency_authority() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    asyncio.run(_exercise_score_manager(normalize_database_url(database_url)))


async def _exercise_duplicate_answer(database_url: str) -> None:
    database = Database(DatabaseSettings(url=database_url, pool_size=2, max_overflow=0))
    try:
        async with database.transaction() as session:
            repository = OperationalRepository(session)
            await repository.upsert_chat({"id": TEST_CHAT_ID, "type": "private"})
            await repository.upsert_user(
                {
                    "id": TEST_USER_ID,
                    "display_name": "Storage test",
                    "global_score": Decimal("0"),
                    "total_answered": 0,
                }
            )
            await repository.upsert_member(
                {
                    "chat_id": TEST_CHAT_ID,
                    "user_id": TEST_USER_ID,
                    "score": Decimal("0"),
                }
            )

        async with database.transaction() as session:
            first = await OperationalRepository(session).record_answer_and_add_score(
                poll_id=TEST_POLL_ID,
                user_id=TEST_USER_ID,
                chat_id=TEST_CHAT_ID,
                points_delta=Decimal("1.5"),
                selected_option=2,
                is_correct=True,
            )
        async with database.transaction() as session:
            second = await OperationalRepository(session).record_answer_and_add_score(
                poll_id=TEST_POLL_ID,
                user_id=TEST_USER_ID,
                chat_id=TEST_CHAT_ID,
                points_delta=Decimal("1.5"),
                selected_option=2,
                is_correct=True,
            )

        async with database.transaction() as session:
            member = await session.scalar(
                select(ChatMember).where(
                    ChatMember.chat_id == TEST_CHAT_ID,
                    ChatMember.user_id == TEST_USER_ID,
                )
            )
            user = await session.get(User, TEST_USER_ID)
            assert first is True
            assert second is False
            assert member is not None and member.score == Decimal("1.500")
            assert member.answered_count == 1
            assert member.correct_answers_count == 1
            assert member.max_consecutive_correct == 1
            assert user is not None and user.global_score == Decimal("1.500")
            assert user.total_answered == 1

            await session.execute(delete(PollAnswer).where(PollAnswer.poll_id == TEST_POLL_ID))
            await session.execute(delete(ChatMember).where(ChatMember.chat_id == TEST_CHAT_ID))
            await session.execute(delete(User).where(User.id == TEST_USER_ID))
            await session.execute(delete(Chat).where(Chat.id == TEST_CHAT_ID))
    finally:
        await database.dispose()


async def _exercise_runtime_round_trip(database_url: str) -> None:
    database = Database(DatabaseSettings(url=database_url, pool_size=2, max_overflow=0))
    storage = PostgresRuntimeStorage(database)
    now = datetime.now(timezone.utc)

    class StateStub:
        chat_settings = {}
        user_scores = {}
        global_settings = {}
        generic_messages_to_delete = defaultdict(dict)

    try:
        await storage.save_chat_settings(
            TEST_CHAT_ID,
            {
                "title": "Runtime test",
                "chat_type": "private",
                "daily_quiz": {
                    "enabled": True,
                    "timezone": "Europe/Moscow",
                    "times_msk": [{"hour": 8, "minute": 5}],
                },
            },
        )
        await storage.sync_member_state(
            TEST_CHAT_ID,
            TEST_USER_ID,
            "Runtime user",
            {
                "name": "Runtime user",
                "score": 4.5,
                "answered_polls": {"p1", "p2"},
                "daily_answered_polls": {"p2"},
                "correct_answers_count": 2,
                "milestones_achieved": {"runtime-achievement"},
                "consecutive_correct": 2,
                "max_consecutive_correct": 3,
                "first_answer_time": now.isoformat(),
                "last_answer_time": now.isoformat(),
                "last_daily_reset": now.date().isoformat(),
            },
            recompute_global=True,
        )
        from datetime import timedelta
        from storage.cleanup import CleanupQueue
        from storage.classic_sessions import ClassicSessions
        await CleanupQueue(database).enqueue(TEST_CHAT_ID, 12345, now + timedelta(seconds=120))
        await ClassicSessions(database).create(
                {
                    "chat_id": TEST_CHAT_ID,
                    "session_id": "runtime-storage-test",
                    "quiz_type": "classic",
                    "quiz_start_time": now.isoformat(),
                    "questions": [],
                }
        )

        state = StateStub()
        active = await storage.load_into_state(state)

        assert state.chat_settings[TEST_CHAT_ID]["title"] == "Runtime test"
        member = state.user_scores[TEST_CHAT_ID][str(TEST_USER_ID)]
        assert member["score"] == 4.5
        assert member["answered_polls"] == {"p1", "p2"}
        assert member["milestones_achieved"] == {"runtime-achievement"}
        assert state.generic_messages_to_delete[TEST_CHAT_ID][12345] == now.timestamp()
        assert active == {}
        async with database.transaction() as session:
            game = await session.scalar(select(Game).where(
                Game.chat_id == TEST_CHAT_ID,
                Game.mode == 'classic',
                Game.is_current.is_(True),
            ))
            assert game and game.state['quiz_type'] == 'classic'
    finally:
        async with database.transaction() as session:
            await session.execute(
                delete(AchievementGrant).where(AchievementGrant.user_id == TEST_USER_ID)
            )
            await session.execute(delete(PollAnswer).where(PollAnswer.user_id == TEST_USER_ID))
            await session.execute(
                delete(MessageCleanupItem).where(MessageCleanupItem.chat_id == TEST_CHAT_ID)
            )
            await session.execute(delete(QuizSession).where(QuizSession.chat_id == TEST_CHAT_ID))
            await session.execute(delete(DailySchedule).where(DailySchedule.chat_id == TEST_CHAT_ID))
            await session.execute(delete(ChatMember).where(ChatMember.chat_id == TEST_CHAT_ID))
            await session.execute(delete(User).where(User.id == TEST_USER_ID))
            await session.execute(delete(Chat).where(Chat.id == TEST_CHAT_ID))
        await database.dispose()


async def _exercise_score_manager(database_url: str) -> None:
    database = Database(DatabaseSettings(url=database_url, pool_size=2, max_overflow=0))
    storage = PostgresRuntimeStorage(database)
    app_config = SimpleNamespace(
        global_settings={"streak_bonuses": {"enabled": False}},
        parsed_chat_achievements={},
        default_chat_settings={},
    )
    state = BotState(app_config)
    data_manager = SimpleNamespace(postgres_storage=storage, state=state)
    manager = ScoreManager(app_config, state, data_manager)
    telegram_user = TelegramUser(
        id=TEST_USER_ID,
        first_name="Runtime user",
        is_bot=False,
    )

    try:
        first = await manager.update_score_and_get_motivation(
            TEST_CHAT_ID,
            telegram_user,
            TEST_SCORE_MANAGER_POLL_ID,
            True,
            "session",
        )
        second = await manager.update_score_and_get_motivation(
            TEST_CHAT_ID,
            telegram_user,
            TEST_SCORE_MANAGER_POLL_ID,
            True,
            "session",
        )

        assert first[0] is True
        assert state.user_scores[TEST_CHAT_ID][str(TEST_USER_ID)]["score"] == 1
        assert state.user_scores[TEST_CHAT_ID][str(TEST_USER_ID)][
            "correct_answers_count"
        ] == 1
        assert second == (False, None, None, None)  # Duplicate is a complete no-op.

        async with database.transaction() as session:
            member = await session.get(ChatMember, (TEST_CHAT_ID, TEST_USER_ID))
            user = await session.get(User, TEST_USER_ID)
            poll_rows = list(
                (
                    await session.scalars(
                        select(PollAnswer).where(
                            PollAnswer.poll_id == TEST_SCORE_MANAGER_POLL_ID
                        )
                    )
                ).all()
            )
            assert member is not None and member.score == Decimal("1.000")
            assert member.correct_answers_count == 1
            assert user is not None and user.global_score == Decimal("1.000")
            assert len(poll_rows) == 1
    finally:
        async with database.transaction() as session:
            await session.execute(
                delete(AchievementGrant).where(AchievementGrant.user_id == TEST_USER_ID)
            )
            await session.execute(
                delete(PollAnswer).where(PollAnswer.user_id == TEST_USER_ID)
            )
            await session.execute(delete(ChatMember).where(ChatMember.chat_id == TEST_CHAT_ID))
            await session.execute(delete(User).where(User.id == TEST_USER_ID))
            await session.execute(delete(Chat).where(Chat.id == TEST_CHAT_ID))
        await database.dispose()
