"""Run against morning_quiz_test, never the bot's development database."""

import asyncio
import os
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select
from telegram import User as TelegramUser

from data_manager import DataManager
from modules.score_manager import ScoreManager
from storage.database import Database, DatabaseSettings, normalize_database_url
from storage.members import MemberService, ScoreConflict
from storage.models import (
    AccountIdentity, AchievementGrant, Chat, ChatMember, Game, PollAnswer,
    MiniAppSession, Room, User, MessageCleanupItem, SystemState,
)
from storage.repositories import OperationalRepository
from storage.runtime import PostgresRuntimeStorage
from web.postgres_admin import install_postgres_admin


CHAT = -900000000002
OTHER_CHAT = -900000000003
USER = 900000000002


@pytest.fixture
def pg_env(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    # Explicit test connection is required; DATABASE_URL alone is never enough.
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("STORAGE_BACKEND", "postgres")
    return normalize_database_url(url)


@asynccontextmanager
async def scenario(url):
    database = Database(DatabaseSettings(url=url, pool_size=5, max_overflow=0))
    try:
        yield database
    finally:
        async with database.transaction() as session:
            chat_ids = [CHAT, OTHER_CHAT, USER, USER + 1]
            user_ids = range(USER, USER + 4)
            await session.execute(delete(SystemState).where(SystemState.key.in_([
                "cleanup_retry_until", f"mafia_lobby:{CHAT}", f"mafia_lobby:{OTHER_CHAT}",
                f"mini_mafia_lobby:{USER}", f"mini_mafia_lobby:{USER + 1}",
            ])))
            await session.execute(delete(MessageCleanupItem).where(MessageCleanupItem.chat_id.in_(chat_ids)))
            await session.execute(delete(Game).where(Game.chat_id.in_(chat_ids)))
            await session.execute(delete(MiniAppSession).where(MiniAppSession.user_id.in_(user_ids)))
            await session.execute(delete(Chat).where(Chat.id.in_(chat_ids)))
            await session.execute(delete(Room).where(
                Room.id.in_([f'telegram:{chat_id}' for chat_id in chat_ids])))
            await session.execute(delete(AccountIdentity).where(
                AccountIdentity.provider == 'telegram',
                AccountIdentity.provider_subject.in_(str(uid) for uid in user_ids),
            ))
            await session.execute(delete(User).where(User.id.in_(user_ids)))
        await database.dispose()


def scorer(database, *, bonuses=False):
    active = SimpleNamespace(scores={})
    state = SimpleNamespace(user_scores={}, get_active_quiz=lambda _: active)
    config = SimpleNamespace(
        global_settings={"streak_bonuses": {
            "enabled": bonuses, "min_streak_for_bonus": 2,
            "base_multiplier": 0.1, "max_multiplier": 1.0,
        }},
        parsed_chat_achievements={1: "{user_name}: {user_score}"},
    )
    data_manager = SimpleNamespace(
        postgres_storage=PostgresRuntimeStorage(database), state=state,
    )
    return ScoreManager(config, state, data_manager)


async def answer(manager, poll, correct=True, chat=CHAT):
    return await manager.update_score_and_get_motivation(
        chat, TelegramUser(USER, "Test", False), poll, correct, "session",
    )


def test_concurrent_answers_use_current_database_streak(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            # Independent bot instances start with empty (stale) caches.
            managers = [scorer(db, bonuses=True) for _ in range(4)]
            results = await asyncio.gather(*[
                answer(m, f"parallel-{i}") for i, m in enumerate(managers)
            ])
            assert all(r[0] for r in results)
            async with db.transaction() as session:
                member = await session.get(ChatMember, (CHAT, USER))
                user = await session.get(User, USER)
                assert member.score == Decimal("4.900")  # 1 + 1.2 + 1.3 + 1.4
                assert member.consecutive_correct == member.max_consecutive_correct == 4
                assert member.answered_count == member.correct_answers_count == 4
                assert len(member.answered_poll_ids) == 4
                assert user.global_score == member.score
                assert user.total_answered == 4
                grants = (await session.scalars(select(AchievementGrant).where(AchievementGrant.user_id == USER))).all()
                assert len(grants) == 1  # Chat milestone is committed exactly once.
    asyncio.run(run())


def test_concurrent_duplicate_does_not_publish_scores_or_messages_twice(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            managers = [scorer(db) for _ in range(3)]
            results = await asyncio.gather(*[answer(m, "same-event") for m in managers])
            assert sum(r[0] for r in results) == 1
            assert all(r == (False, None, None, None) for r in results if not r[0])
            assert sum(m.state.get_active_quiz(CHAT).scores.get(str(USER), {}).get("score", 0) for m in managers) == 1
            async with db.transaction() as session:
                assert (await session.get(ChatMember, (CHAT, USER))).score == Decimal(1)
                assert (await session.get(User, USER)).total_answered == 1
    asyncio.run(run())


def test_admin_change_survives_stale_bot_cache_and_autosave(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            manager = scorer(db)
            await answer(manager, "before-admin")
            service = MemberService(db)
            assert await service.set_score(CHAT, USER, Decimal(40), Decimal(1)) == Decimal(1)
            with pytest.raises(ScoreConflict):
                await service.set_score(CHAT, USER, Decimal(99), Decimal(1))
            # Legacy autosave cannot overwrite the administrator's correction.
            DataManager.save_user_data(manager.data_manager, CHAT)
            DataManager.update_global_statistics(manager.data_manager)
            with pytest.raises(RuntimeError):
                await manager.postgres_storage.save_chat_users(CHAT, manager.state.user_scores[CHAT])
            with pytest.raises(RuntimeError):
                await manager.postgres_storage.sync_member_state(CHAT, USER, "Test", {"score": 1})
            await answer(manager, "after-admin", correct=False)
            async with db.transaction() as session:
                member = await session.get(ChatMember, (CHAT, USER))
                user = await session.get(User, USER)
                assert member.score == user.global_score == Decimal("39.500")
                assert member.answered_count == user.total_answered == 2
                assert member.consecutive_correct == 0
                assert member.max_consecutive_correct == 1
            assert manager.state.user_scores[CHAT][str(USER)]["score"] == 39.5
    asyncio.run(run())


def test_admin_edit_waits_for_answer_transaction(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            manager = scorer(db)
            await answer(manager, "seed")
            locked, release = asyncio.Event(), asyncio.Event()

            async def transition(data):
                data["score"] += 1
                data["answered_polls"].add("held-answer")
                locked.set()
                await release.wait()

            task = asyncio.create_task(MemberService(db).apply_answer(
                chat_id=CHAT, user_id=USER, display_name="Test", answer_id="held-answer",
                is_correct=True, transition=transition,
            ))
            await asyncio.wait_for(locked.wait(), 5)
            edit = asyncio.create_task(MemberService(db).set_score(CHAT, USER, Decimal(50), Decimal(1)))
            release.set()
            await asyncio.wait_for(task, 5)
            with pytest.raises(ScoreConflict):
                await asyncio.wait_for(edit, 5)
            async with db.transaction() as session:
                assert (await session.get(ChatMember, (CHAT, USER))).score == Decimal(2)
    asyncio.run(run())


def test_failed_final_write_rolls_back_ledger_profile_and_awards(pg_env, monkeypatch):
    async def run():
        async with scenario(pg_env) as db:
            manager = scorer(db)
            await answer(manager, "seed")
            previous = dict(manager.state.user_scores[CHAT][str(USER)])
            original = OperationalRepository.add_achievement_codes

            async def fail_after_awards(self, *args, **kwargs):
                await original(self, *args, **kwargs)
                raise RuntimeError("injected failure after membership/ledger/award writes")

            with monkeypatch.context() as patch:
                patch.setattr(OperationalRepository, "add_achievement_codes", fail_after_awards)
                with pytest.raises(RuntimeError, match="injected failure"):
                    await answer(manager, "rollback")
            assert manager.state.user_scores[CHAT][str(USER)] == previous
            assert manager.state.get_active_quiz(CHAT).scores[str(USER)]["score"] == 1
            async with db.transaction() as session:
                assert await session.get(PollAnswer, ("rollback", USER)) is None
                member = await session.get(ChatMember, (CHAT, USER))
                assert member.score == Decimal(1) and member.answered_count == 1
                assert member.milestone_codes == []
                assert not (await session.scalars(select(AchievementGrant).where(AchievementGrant.user_id == USER))).all()
            assert (await answer(manager, "rollback"))[0]
    asyncio.run(run())


def test_imported_answer_history_prevents_reaward_after_daily_reset(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            manager = scorer(db)
            await manager.postgres_storage.sync_member_state(CHAT, USER, "Imported", {
                "score": 12, "answered_polls": {"legacy"},
                "last_daily_reset": "2020-01-01", "daily_answered_polls": set(),
            }, recompute_global=True)
            assert await answer(manager, "legacy") == (False, None, None, None)
            async with db.transaction() as session:
                assert (await session.get(ChatMember, (CHAT, USER))).score == Decimal(12)
                assert await session.get(PollAnswer, ("legacy", USER)) is None
    asyncio.run(run())


def test_photo_award_is_idempotent_and_preserves_classic_counters(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            manager = scorer(db)
            await answer(manager, "classic")
            await MemberService(db).set_score(CHAT, USER, Decimal(20))
            results = await asyncio.gather(*[
                scorer(db).award_photo_answer(CHAT, USER, "photo:session:0", 5.5)
                for _ in range(3)
            ])
            assert sum(results) == 1
            async with db.transaction() as session:
                member = await session.get(ChatMember, (CHAT, USER))
                user = await session.get(User, USER)
                assert member.score == user.global_score == Decimal("25.500")
                assert user.display_name == "Test"  # Photo events cannot rename from stale cache.
                assert member.answered_count == user.total_answered == 1
                assert member.correct_answers_count == 2
                assert member.consecutive_correct == 1
                assert member.answered_poll_ids == ["classic"]
                assert (await session.get(PollAnswer, ("photo:session:0", USER))).payload["quiz_type"] == "photo"
    asyncio.run(run())


def test_answers_in_two_chats_preserve_global_total(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            await asyncio.gather(
                answer(scorer(db), "chat-a"),
                answer(scorer(db), "chat-b", chat=OTHER_CHAT),
            )
            await MemberService(db).set_score(CHAT, USER, Decimal(10))
            async with db.transaction() as session:
                user = await session.get(User, USER)
                assert user.global_score == Decimal(11) and user.total_answered == 2
    asyncio.run(run())


def test_pg_admin_reads_live_scores_and_blocks_legacy_mutations(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            await answer(scorer(db), "api-seed")
            app = FastAPI()
            install_postgres_admin(app)
            fallback = Mock(side_effect=AssertionError("JSON route must not execute"))

            @app.put("/api/users/{user_id}/score")
            async def legacy_score(user_id: int):
                return fallback()

            @app.post("/api/users/{user_id}/reset-stats")
            async def legacy_reset(user_id: int):
                return fallback()

            @app.get("/api/analytics/global")
            async def legacy_global():
                return fallback()

            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                    assert (await client.get("/api/storage/status")).json()["backend"] == "postgres"
                    assert (await client.get("/api/chats?use_telegram_api=true")).json()[0]["id"] == CHAT
                    path = f"/api/users/{USER}/score"
                    response = await client.put(path, params={"chat_id": CHAT, "new_score": "7.125", "expected_score": "1"})
                    assert response.status_code == 200, response.text
                    assert response.json()["old_score"] == 1
                    response = await client.put(path, params={"chat_id": CHAT, "new_score": "8", "expected_score": "1"})
                    assert response.status_code == 409
                    for invalid in ["NaN", "Infinity", "-Infinity", "100000000000", "1.0001"]:
                        response = await client.put(path, params={"chat_id": CHAT, "new_score": invalid})
                        assert response.status_code == 422, response.text
                    response = await client.put(path, params={"chat_id": CHAT, "new_score": "8", "expected_score": "NaN"})
                    assert response.status_code == 422
                    response = await client.put(path, params={"chat_id": OTHER_CHAT, "new_score": "8"})
                    assert response.status_code == 404
                    assert (await client.get(f"/api/chats/{OTHER_CHAT}/settings")).status_code == 404
                    detail = (await client.get(f"/api/analytics/chats/{CHAT}")).json()
                    assert detail["users"][str(USER)]["score"] == 7.125
                    assert detail["stats"]["total_score"] == 7.125
                    users = (await client.get("/api/users")).json()["users"]
                    assert users[0]["total_score"] == 7.125 and users[0]["total_answered"] == 1
                    assert (await client.post(f"/api/users/{USER}/reset-stats")).status_code == 501
                    assert (await client.get("/api/analytics/global")).status_code == 501
                    assert (await client.delete(f"/api/chats/{CHAT}")).status_code == 501
                    fallback.assert_not_called()
    asyncio.run(run())


def test_json_admin_keeps_original_routes(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "json")
    app = FastAPI()
    install_postgres_admin(app)
    assert not app.user_middleware
    assert not any(r.path.startswith("/api/") for r in app.routes)

    async def verify_fail_closed():
        with pytest.raises(RuntimeError, match="requires STORAGE_BACKEND=postgres"):
            async with app.router.lifespan_context(app):
                pytest.fail("JSON admin runtime must never start")

    asyncio.run(verify_fail_closed())
