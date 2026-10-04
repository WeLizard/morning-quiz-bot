import asyncio
from contextvars import ContextVar
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from data_manager import DataManager
from handlers.daily_quiz_scheduler import DailyQuizScheduler
from handlers.quiz_manager import QuizManager
from handlers.rating_handlers import RatingHandlers
from storage.members import MemberService
from storage.models import Chat, DailySchedule
from storage.repositories import OperationalRepository
from storage.runtime import PostgresRuntimeStorage
from storage.score_queries import ScoreQueries
from storage.settings import SettingsConflict, SettingsService
from tests.test_postgres_members import CHAT, OTHER_CHAT, USER, answer, pg_env, scenario, scorer
from web.postgres_admin import install_postgres_admin


DEFAULTS = {
    "default_num_questions": 10, "default_open_period_seconds": 30,
    "daily_quiz": {"enabled": False, "times_msk": [{"hour": 9, "minute": 0}], "timezone": "Europe/Moscow"},
    "daily_wisdom": {"enabled": False, "time": "10:00"},
}


def data_manager(db):
    manager = DataManager.__new__(DataManager)
    manager.postgres_storage = PostgresRuntimeStorage(db)
    manager.app_config = SimpleNamespace(default_chat_settings=deepcopy(DEFAULTS))
    manager.state = SimpleNamespace(chat_settings={}, generic_messages_to_delete={})
    manager._settings_locks = {}
    manager._settings_read_revisions = ContextVar("test_read_revisions", default=None)
    return manager


def update_stub():
    return SimpleNamespace(
        message=SimpleNamespace(reply_text=AsyncMock(return_value=SimpleNamespace(message_id=42))),
        effective_chat=SimpleNamespace(id=CHAT, title="Тестовый чат"),
        effective_user=SimpleNamespace(id=USER, first_name="Test"),
    )


def test_all_score_reads_see_admin_edit_without_mutating_cache(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            manager = scorer(db)
            await answer(manager, "first")
            await answer(manager, "second", chat=OTHER_CHAT)
            cache = deepcopy(manager.state.user_scores)
            await MemberService(db).set_score(CHAT, USER, Decimal("24.5"))
            assert (await manager.get_chat_rating(CHAT))[0]["score"] == 24.5
            assert (await manager.get_global_rating())[0]["score"] == 25.5
            assert (await manager.get_user_stats_in_chat(CHAT, str(USER)))["score"] == 24.5
            assert (await manager.get_current_chat_user_stats(str(USER), CHAT))["total_score"] == 24.5
            assert (await manager.get_global_user_stats(str(USER)))["total_score"] == 25.5
            profiles = await manager.get_session_profiles(CHAT, [str(USER), str(USER + 1)])
            assert profiles[str(USER)]["chat"]["answered_polls"] == 1
            assert profiles[str(USER)]["global"]["answered_polls"] == 2
            assert str(USER + 1) not in profiles
            assert await manager.get_session_profiles(CHAT, []) == {}
            assert await manager.get_global_rating(0) == []
            assert manager.state.user_scores == cache
            snapshot = await ScoreQueries(db).chat_statistics(CHAT)
            assert snapshot["users"][str(USER)]["score"] == 24.5
    asyncio.run(run())


def test_telegram_commands_read_database_not_json_or_cache(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            manager = scorer(db)
            await answer(manager, "command")
            await MemberService(db).set_score(CHAT, USER, Decimal(42))
            handlers = RatingHandlers(SimpleNamespace(rating_display_limit=10), manager)
            update = update_stub()
            state = SimpleNamespace(add_message_for_deletion=Mock())
            context = SimpleNamespace(bot_data={"bot_state": state})
            await handlers.top_global_command(update, context)
            assert "42" in update.message.reply_text.call_args.args[0]
            state.add_message_for_deletion.assert_called_with(CHAT, 42)
            await handlers.my_stats_command(update, context)
            assert "42" in update.message.reply_text.call_args.args[0]
            quiz = QuizManager.__new__(QuizManager)
            quiz.data_manager = SimpleNamespace(postgres_storage=PostgresRuntimeStorage(db))
            quiz.category_manager = Mock()
            await quiz.chat_stats_command(update, context)
            assert "42" in update.message.reply_text.call_args.args[0]
            quiz.category_manager.get_category_usage_stats.assert_not_called()
    asyncio.run(run())


def test_score_read_failure_is_explicit_not_a_stale_fallback():
    async def run():
        manager = SimpleNamespace(
            get_global_rating=AsyncMock(side_effect=RuntimeError("offline")),
            get_session_profiles=AsyncMock(side_effect=RuntimeError("offline")),
        )
        handlers = RatingHandlers(SimpleNamespace(rating_display_limit=10), manager)
        update, context = update_stub(), SimpleNamespace(bot_data={})
        await handlers.top_global_command(update, context)
        assert "временно недоступна" in update.message.reply_text.call_args.args[0]
        await handlers.my_stats_command(update, context)
        assert "временно недоступна" in update.message.reply_text.call_args.args[0]
    asyncio.run(run())


def test_json_async_read_contract_and_session_error_display():
    async def run():
        manager = scorer(None)
        manager.postgres_storage = None
        manager.state.user_scores = {CHAT: {str(USER): {"name": "Test", "score": 4.5, "answered_polls": {"a", "b"}, "correct_answers_count": 1}}}
        assert (await manager.get_chat_rating(CHAT))[0]["score"] == 4.5
        assert (await manager.get_global_rating())[0]["score"] == 4.5
        profile = (await manager.get_session_profiles(CHAT, [str(USER)]))[str(USER)]
        assert profile["chat"]["answered_polls_count"] == profile["global"]["answered_polls"] == 2
        text = manager.format_scores([{"name": "Test", "score": 1, "correct_count": 1,
                                      "statistics_available": False}], "Итоги", True, 3)
        assert "1/3" in text and "статистика временно недоступна" in text
        assert "0.0" not in text and "👑" not in text
    asyncio.run(run())


def test_concurrent_settings_revision_rejects_stale_writer(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            service = SettingsService(db)
            seed = await service.patch_paths(CHAT, [(["title"], "Test")], defaults=DEFAULTS, expected_revision=0)
            results = await asyncio.gather(*[
                service.patch_paths(CHAT, [(["default_num_questions"], n)], expected_revision=seed.revision)
                for n in [12, 17]
            ], return_exceptions=True)
            assert sum(isinstance(r, SettingsConflict) for r in results) == 1
            current = await service.get(CHAT)
            assert current.revision == seed.revision + 1
            assert current.values["default_num_questions"] in {12, 17}
            assert current.values["daily_quiz"] == DEFAULTS["daily_quiz"]
    asyncio.run(run())


def test_disjoint_settings_patch_and_schedules_are_preserved(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            service = SettingsService(db)
            await service.patch_paths(CHAT, [(["title"], "Test")], defaults=DEFAULTS)
            await asyncio.gather(
                service.patch_paths(CHAT, [(["daily_quiz", "enabled"], True)]),
                service.patch_paths(CHAT, [(["daily_quiz", "timezone"], "Europe/Istanbul")]),
            )
            current = await service.get(CHAT)
            assert current.values["daily_quiz"]["enabled"] is True
            unchanged = await service.patch_paths(CHAT, [(["daily_quiz", "enabled"], True)], expected_revision=current.revision)
            assert unchanged.revision == current.revision
            async with db.transaction() as session:
                schedules = (await session.scalars(select(DailySchedule).where(DailySchedule.chat_id == CHAT))).all()
                assert len(schedules) == 2
                assert all(s.timezone == "Europe/Istanbul" for s in schedules)
                assert next(s for s in schedules if s.kind == "quiz").enabled
    asyncio.run(run())


def test_datamanager_detects_admin_conflict_and_disables_snapshot_autosave(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            manager = data_manager(db)
            await manager.update_chat_setting(CHAT, ["default_num_questions"], 12)
            stale = deepcopy(manager.state.chat_settings[CHAT])
            external = await SettingsService(db).patch_paths(CHAT, [(["default_num_questions"], 20)])
            manager.save_chat_settings()
            manager.state._chat_settings_modified = {CHAT}
            manager.save_modified_chat_settings()
            await manager.save_modified_chat_settings_async()
            await manager.save_all_data_async()
            assert (await SettingsService(db).get(CHAT)).values["default_num_questions"] == 20
            with pytest.raises(RuntimeError):
                await manager.postgres_storage.save_chat_settings(CHAT, stale)
            with pytest.raises(SettingsConflict):
                await manager.update_chat_setting(CHAT, ["default_open_period_seconds"], 60)
            assert manager.state.chat_settings[CHAT] == external.values
            await manager.update_quiz_setting(CHAT, "num_questions", 15)
            saved = await SettingsService(db).get(CHAT)
            assert saved.values["default_num_questions"] == saved.values["quiz"]["num_questions"] == 15
            assert saved.revision == external.revision + 1  # Mirrored keys commit once.
    asyncio.run(run())


def test_callback_revision_is_not_replaced_by_another_callback_read(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            manager = data_manager(db)
            await manager.update_chat_setting(CHAT, ["enabled_categories"], ["A"])
            observed, release = asyncio.Event(), asyncio.Event()

            async def stale_callback():
                await manager.get_chat_settings_async(CHAT)
                observed.set()
                await release.wait()
                with pytest.raises(SettingsConflict):
                    await manager.update_chat_setting(CHAT, ["enabled_categories"], ["A", "B"])

            task = asyncio.create_task(stale_callback())
            await asyncio.wait_for(observed.wait(), 3)
            await SettingsService(db).patch_paths(CHAT, [(["enabled_categories"], ["C"])])
            await manager.get_chat_settings_async(CHAT)  # Refreshes shared cache, not task's observed revision.
            release.set()
            await asyncio.wait_for(task, 3)
            assert (await SettingsService(db).get(CHAT)).values["enabled_categories"] == ["C"]
    asyncio.run(run())


def test_settings_failure_rolls_back_revision_schedules_and_cache(pg_env, monkeypatch):
    async def run():
        async with scenario(pg_env) as db:
            manager = data_manager(db)
            await manager.update_chat_setting(CHAT, ["daily_quiz", "enabled"], False)
            before = await SettingsService(db).get(CHAT)
            with monkeypatch.context() as patch:
                patch.setattr(OperationalRepository, "upsert_schedule", AsyncMock(side_effect=RuntimeError("failed schedule")))
                with pytest.raises(RuntimeError, match="failed schedule"):
                    await manager.update_chat_setting(CHAT, ["daily_quiz", "enabled"], True)
            assert await SettingsService(db).get(CHAT) == before
            assert manager.state.chat_settings[CHAT] == before.values
            assert manager.state.chat_settings_revisions[CHAT] == before.revision
    asyncio.run(run())


def test_settings_reset_is_persisted_and_read_result_is_detached(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            manager = data_manager(db)
            await manager.update_chat_setting(CHAT, ["default_num_questions"], 30)
            await manager.update_chat_setting(CHAT, ["daily_quiz", "enabled"], True)
            read = await manager.get_chat_settings_async(CHAT)
            read["daily_quiz"]["times_msk"].append({"hour": 20, "minute": 0})
            assert len(manager.state.chat_settings[CHAT]["daily_quiz"]["times_msk"]) == 1
            await manager.reset_chat_settings(CHAT)
            assert (await SettingsService(db).get(CHAT)).values == DEFAULTS
            async with db.transaction() as session:
                schedules = (await session.scalars(select(DailySchedule).where(DailySchedule.chat_id == CHAT))).all()
                assert all(not s.enabled for s in schedules)
    asyncio.run(run())


def test_admin_settings_api_requires_revision_and_rejects_invalid_schedule_atomically(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            await SettingsService(db).patch_paths(CHAT, [(["title"], "Test")], defaults=DEFAULTS)
            app = FastAPI()
            install_postgres_admin(app)

            @app.put("/api/chats/{chat_id}/settings")
            async def legacy_settings(chat_id: int):
                raise AssertionError("Legacy settings handler must never run")

            async with app.router.lifespan_context(app):
                parameters = app.openapi()["paths"]["/api/chats/{chat_id}/settings"]["put"]["parameters"]
                assert any(p["name"] == "expected_revision" for p in parameters)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                    path = f"/api/chats/{CHAT}/settings"
                    response = await client.get(path)
                    revision = response.headers["x-settings-revision"]
                    assert response.headers["etag"] == f'"{revision}"'
                    assert (await client.put(path, json={"default_num_questions": 17})).status_code == 428
                    result = await client.put(path, params={"expected_revision": revision}, json={"default_num_questions": 17})
                    assert result.status_code == 200, result.text
                    assert result.json()["settings"]["quiz"]["num_questions"] == 17
                    assert (await client.put(path, params={"expected_revision": revision}, json={"default_num_questions": 22})).status_code == 409
                    new_revision = result.json()["revision"]
                    response = await client.put(path, params={"expected_revision": new_revision}, json={"default_num_questions": 22, "daily_quiz": {"enabled": True, "timezone": "Not/AZone"}})
                    assert response.status_code == 422
                    assert (await SettingsService(db).get(CHAT)).values["default_num_questions"] == 17
                    assert (await client.put(path, params={"expected_revision": new_revision}, json={"default_num_questions": 0})).status_code == 422
                    assert (await client.put(path, params={"expected_revision": new_revision}, json={"subscription": {}})).status_code == 422
                    assert (await client.put(f"/api/chats/{OTHER_CHAT}/settings", params={"expected_revision": 0}, json={"default_num_questions": 17})).status_code == 404
    asyncio.run(run())


def test_scheduler_keeps_working_jobs_when_settings_read_fails():
    async def run():
        job = SimpleNamespace(name=f"daily_quiz_for_chat_{CHAT}_time_idx_0", schedule_removal=Mock())
        scheduler = DailyQuizScheduler.__new__(DailyQuizScheduler)
        scheduler.application = SimpleNamespace(job_queue=SimpleNamespace(jobs=lambda: [job]))
        scheduler.data_manager = SimpleNamespace(get_chat_settings_async=AsyncMock(side_effect=RuntimeError("offline")))
        with pytest.raises(RuntimeError, match="offline"):
            await scheduler.reschedule_job_for_chat(CHAT)
        job.schedule_removal.assert_not_called()
    asyncio.run(run())
