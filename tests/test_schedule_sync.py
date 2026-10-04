"""Real PTB/APScheduler queues, isolated PG, no Telegram connection or bot start."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from sqlalchemy import delete, select, update
from telegram.ext import JobQueue

from tests.test_postgres_members import CHAT, OTHER_CHAT, pg_env, scenario
from tests.test_postgres_reads_settings import DEFAULTS, data_manager
from handlers.config_handlers import (
    ConfigHandlers, CTX_ADMIN_CFG_CHAT_ID, CTX_INPUT_TARGET_KEY_PATH,
    CTX_INPUT_CONSTRAINTS, CTX_CURRENT_MENU_SENDER_CB_NAME,
    CB_ADM_DAILY_TIME_REMOVE, CFG_DAILY_TIMES_MENU,
)
from handlers.daily_quiz_scheduler import DailyQuizScheduler
from handlers.wisdom_scheduler import WisdomScheduler
from modules.schedule_sync import ScheduleSync
from storage.models import Chat, DailySchedule, SystemState
from storage.repositories import OperationalRepository
from storage.runtime import PostgresRuntimeStorage
from storage.schedule_plan import build_schedule_plan, validate_schedule_settings
from storage.settings import SettingsService
from web.postgres_admin import install_postgres_admin


def workers(db):
    config = SimpleNamespace(
        default_chat_settings=deepcopy(DEFAULTS), job_grace_period_seconds=30,
        daily_quiz_defaults={"num_questions": 10, "interval_seconds": 60, "categories_mode": "random"},
        quiz_types_config={},
    )
    manager = SimpleNamespace(postgres_storage=PostgresRuntimeStorage(db))
    app = SimpleNamespace(job_queue=JobQueue(), bot=SimpleNamespace(send_message=AsyncMock()))
    daily = DailyQuizScheduler(config, SimpleNamespace(get_active_quiz=lambda _: None), manager,
                               SimpleNamespace(_initiate_quiz_session=AsyncMock()), app)
    wisdom = WisdomScheduler.__new__(WisdomScheduler)
    wisdom.app_config, wisdom.data_manager, wisdom.application = config, manager, app
    wisdom.scheduler = AsyncIOScheduler(timezone="UTC")
    wisdom.openrouter_client = wisdom.category_manager = None
    wisdom._get_random_wisdom = Mock(return_value="Тестовая мудрость")
    return ScheduleSync(db, config, daily, wisdom)


async def seed(db, chat_id=CHAT):
    return await SettingsService(db).patch_paths(chat_id, [(["daily_quiz", "enabled"], True),
        (["daily_wisdom", "enabled"], True)], defaults=DEFAULTS)


def job_ids(sync):
    return ([j.name for j in sync.daily.application.job_queue.jobs()],
            [j.id for j in sync.wisdom.scheduler.get_jobs()])


def test_plan_token_is_canonical_and_excludes_gameplay_settings():
    values = deepcopy(DEFAULTS)
    values["daily_quiz"].update(enabled=True, times_msk=[{"hour": 18, "minute": 30}, {"hour": 9, "minute": 0}])
    plan = build_schedule_plan(values, "quiz")
    values["daily_quiz"]["times_msk"].reverse()
    values["daily_quiz"]["num_questions"] = 25
    assert build_schedule_plan(values, "quiz") == plan
    assert plan.times == ((9, 0), (18, 30))
    values["daily_quiz"]["timezone"] = "Europe/Berlin"
    assert build_schedule_plan(values, "quiz").token != plan.token
    values["daily_quiz"]["enabled"] = False
    assert not build_schedule_plan(values, "quiz").times


@pytest.mark.parametrize("key,value", [
    ("enabled", "false"), ("timezone", "Not/AZone"),
    ("times_msk", [{"hour": True, "minute": 0}]),
    ("times_msk", [{"hour": 25, "minute": 0}]),
    ("times_msk", [{"hour": 9, "minute": 0}] * 2),
])
def test_invalid_disabled_schedules_are_rejected(key, value):
    values = deepcopy(DEFAULTS)
    values["daily_quiz"][key] = value
    with pytest.raises(ValueError):
        validate_schedule_settings(values)


def test_real_cron_triggers_follow_named_timezone_in_winter_and_summer():
    sync = workers(None)
    values = deepcopy(DEFAULTS)
    values["daily_quiz"].update(enabled=True, timezone="Europe/Berlin")
    values["daily_wisdom"].update(enabled=True, time="09:00")
    sync.daily.apply_postgres_plan(CHAT, build_schedule_plan(values, "quiz"))
    sync.wisdom.apply_postgres_plan(CHAT, build_schedule_plan(values, "wisdom"))
    triggers = [sync.daily.application.job_queue.jobs()[0].job.trigger,
                sync.wisdom.scheduler.get_jobs()[0].trigger]
    for trigger in triggers:
        assert str(trigger.timezone) == "Europe/Berlin"
        for month, utc_hour in ((1, 8), (7, 7)):
            fire = trigger.get_next_fire_time(None, datetime(2026, month, 15, tzinfo=timezone.utc))
            assert fire.hour == 9
            assert fire.astimezone(timezone.utc).hour == utc_hour


def test_reconciliation_is_idempotent_repairs_jobs_and_recovers_after_restart(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            saved = await seed(db)
            sync = workers(db)
            assert (await sync.run_once())["applied_revisions"][str(CHAT)] == saved.revision
            before = job_ids(sync)
            original = sync.daily.application.job_queue.jobs()[0]
            await sync.run_once()
            assert job_ids(sync) == before
            assert sync.daily.application.job_queue.jobs()[0] is original
            original.schedule_removal()
            await sync.run_once()
            assert job_ids(sync) == before
            restarted = workers(db)
            await restarted.run_once()
            assert job_ids(restarted) == before
            await SettingsService(db).patch_paths(CHAT, [(["daily_quiz", "timezone"], "Europe/Berlin"),
                (["daily_quiz", "times_msk"], [{"hour": 11, "minute": 15}, {"hour": 18, "minute": 0}])])
            await sync.run_once()
            after = job_ids(sync)
            assert list(map(len, after)) == [2, 1]
            assert set(before[0] + before[1]).isdisjoint(after[0] + after[1])
            await SettingsService(db).patch_paths(CHAT, [(["daily_quiz", "enabled"], False),
                                                       (["daily_wisdom", "enabled"], False)])
            await sync.run_once()
            assert job_ids(sync) == ([], [])
    asyncio.run(run())


def test_inactive_or_deleted_chats_lose_jobs(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            await seed(db)
            sync = workers(db)
            await sync.run_once()
            async with db.transaction() as session:
                await session.execute(update(Chat).where(Chat.id == CHAT).values(is_active=False))
            await sync.run_once()
            assert job_ids(sync) == ([], [])
            async with db.transaction() as session:
                await session.execute(update(Chat).where(Chat.id == CHAT).values(is_active=True))
            await sync.run_once()
            assert all(job_ids(sync))
            async with db.transaction() as session:
                await session.execute(delete(Chat).where(Chat.id == CHAT))
            await sync.run_once()
            assert job_ids(sync) == ([], [])
            assert not sync._known_chats
    asyncio.run(run())


def test_legacy_enabled_quiz_without_times_does_not_block_wisdom(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            saved = await seed(db)
            legacy = deepcopy(saved.values)
            legacy["daily_quiz"]["times_msk"] = []
            async with db.transaction() as session:
                await session.execute(update(Chat).where(Chat.id == CHAT).values(settings=legacy))
            sync = workers(db)
            status = await sync.run_once()
            assert not status["failed_chats"]
            assert list(map(len, job_ids(sync))) == [0, 1]
            assert (await SettingsService(db).get(CHAT)).values == legacy
    asyncio.run(run())


def test_database_outage_does_not_remove_jobs_and_next_tick_recovers(pg_env, monkeypatch):
    async def run():
        async with scenario(pg_env) as db:
            await seed(db)
            sync = workers(db)
            await sync.run_once()
            before = job_ids(sync)
            with monkeypatch.context() as patch:
                patch.setattr(sync.source, "read", AsyncMock(side_effect=RuntimeError("offline")))
                with pytest.raises(RuntimeError, match="offline"):
                    await sync.run_once()
                await sync.tick()  # Repeating callback must survive the outage.
            assert job_ids(sync) == before
            assert not (await sync.run_once())["failed_chats"]
    asyncio.run(run())


@pytest.mark.parametrize("failed_kind", ["quiz", "wisdom"])
def test_failed_add_retains_previous_jobs_and_retries(pg_env, monkeypatch, failed_kind):
    async def run():
        async with scenario(pg_env) as db:
            await seed(db)
            await seed(db, OTHER_CHAT)
            sync = workers(db)
            await sync.run_once()
            old = job_ids(sync)
            await SettingsService(db).patch_paths(CHAT, [(["daily_quiz", "timezone"], "Europe/Berlin"),
                (["daily_quiz", "times_msk"], [{"hour": 11, "minute": 0}, {"hour": 18, "minute": 0}])])
            scheduler = (sync.daily.application.job_queue.scheduler if failed_kind == "quiz" else sync.wisdom.scheduler)
            original = scheduler.add_job
            calls = 0

            def fail(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == (2 if failed_kind == "quiz" else 1):
                    raise RuntimeError("cannot add")
                return original(*args, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(scheduler, "add_job", fail)
                status = await sync.run_once()
            assert status["failed_chats"] == {str(CHAT): "RuntimeError"}
            assert str(OTHER_CHAT) in status["applied_revisions"]
            assert str(CHAT) not in status["applied_revisions"]
            # The two scheduler installations are not a distributed transaction:
            # on wisdom failure, the quiz may already be updated, but not vice versa.
            index = 0 if failed_kind == "quiz" else 1
            assert job_ids(sync)[index] == old[index]
            assert not (await sync.run_once())["failed_chats"]
            assert list(map(len, job_ids(sync))) == [3, 2]
    asyncio.run(run())


def test_stale_callbacks_skip_and_current_quiz_reads_latest_gameplay_settings(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            await seed(db)
            sync = workers(db)
            await sync.run_once()
            job = sync.daily.application.job_queue.jobs()[0]
            token = sync.wisdom.scheduler.get_jobs()[0].kwargs["schedule_token"]
            await SettingsService(db).patch_paths(CHAT, [(["daily_quiz", "num_questions"], 17)])
            await sync.daily._trigger_daily_quiz_job(SimpleNamespace(job=job))
            launch = sync.daily.quiz_manager._initiate_quiz_session
            launch.assert_awaited_once()
            assert launch.call_args.kwargs["num_questions"] == 17
            await sync.wisdom._send_daily_wisdom(str(CHAT), schedule_token=token)
            send = sync.wisdom.application.bot.send_message
            send.assert_awaited_once()
            launch.reset_mock()
            send.reset_mock()
            await SettingsService(db).patch_paths(CHAT, [(["daily_quiz", "timezone"], "Europe/Berlin")])
            await sync.daily._trigger_daily_quiz_job(SimpleNamespace(job=job))
            await sync.wisdom._send_daily_wisdom(str(CHAT), schedule_token=token)
            await sync.wisdom._send_daily_wisdom(str(CHAT))  # No unversioned PG callbacks.
            launch.assert_not_awaited()
            send.assert_not_awaited()
            await sync.run_once()
            job = sync.daily.application.job_queue.jobs()[0]
            await SettingsService(db).patch_paths(CHAT, [(["daily_quiz", "enabled"], False)])
            await sync.daily._trigger_daily_quiz_job(SimpleNamespace(job=job))
            launch.assert_not_awaited()
    asyncio.run(run())


def test_wisdom_disabled_during_generation_is_not_sent(pg_env, monkeypatch):
    async def run():
        async with scenario(pg_env) as db:
            await seed(db)
            sync = workers(db)
            await sync.run_once()
            token = sync.wisdom.scheduler.get_jobs()[0].kwargs["schedule_token"]

            async def generate(**kwargs):
                await SettingsService(db).patch_paths(CHAT, [(["daily_wisdom", "enabled"], False)])
                return "Не отправлять"

            sync.wisdom.openrouter_client = SimpleNamespace(client=True, generate_fun_fact=AsyncMock(side_effect=generate))
            monkeypatch.setattr("handlers.wisdom_scheduler.random.choice", lambda _: True)
            await sync.wisdom._send_daily_wisdom(str(CHAT), schedule_token=token)
            sync.wisdom.openrouter_client.generate_fun_fact.assert_awaited_once()
            sync.wisdom.application.bot.send_message.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('failed', [False, True])
def test_wisdom_empty_or_failed_ai_uses_static_fallback(pg_env, monkeypatch, failed):
    async def run():
        async with scenario(pg_env) as db:
            await seed(db)
            sync = workers(db)
            await sync.run_once()
            token = sync.wisdom.scheduler.get_jobs()[0].kwargs['schedule_token']
            generate = AsyncMock(side_effect=RuntimeError('offline') if failed else None, return_value=None)
            sync.wisdom.openrouter_client = SimpleNamespace(client=True, generate_fun_fact=generate)
            monkeypatch.setattr('handlers.wisdom_scheduler.random.choice', lambda _: True)
            await sync.wisdom._send_daily_wisdom(str(CHAT), schedule_token=token)
            assert 'Тестовая мудрость' in sync.wisdom.application.bot.send_message.await_args.kwargs['text']
    asyncio.run(run())


def test_sync_installs_bounded_non_overlapping_repeating_job():
    async def run():
        sync = workers(None)
        queue = sync.daily.application.job_queue
        queue.scheduler.start(paused=True)
        try:
            sync.install(queue)
            sync.install(queue)
            jobs = queue.scheduler.get_jobs()
            assert len(jobs) == 1
            assert jobs[0].id == "postgres_schedule_sync"
            assert jobs[0].trigger.interval.total_seconds() == 15
            assert jobs[0].coalesce and jobs[0].max_instances == 1
        finally:
            queue.scheduler.shutdown(wait=False)
            await asyncio.sleep(0)
    asyncio.run(run())


def test_chat_menu_adds_time_once_and_keeps_last_enabled_time(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            saved = await seed(db)
            handlers = ConfigHandlers.__new__(ConfigHandlers)
            handlers.data_manager = data_manager(db)
            handlers.app_config = SimpleNamespace(max_daily_quiz_times_per_chat=5)
            handlers._safe_reschedule_job_for_chat = AsyncMock()
            handlers._send_daily_times_menu = AsyncMock()
            handlers._send_main_cfg_menu = AsyncMock()
            handlers._update_config_message = AsyncMock()
            handlers.daily_quiz_scheduler_ref = True
            update = SimpleNamespace(message=SimpleNamespace(text="18:5", from_user=None, delete=AsyncMock()))
            context = SimpleNamespace(chat_data={
                CTX_ADMIN_CFG_CHAT_ID: CHAT, CTX_INPUT_TARGET_KEY_PATH: ["daily_quiz", "times_msk"],
                CTX_INPUT_CONSTRAINTS: {"type": "time", "action": "add_to_list"},
                CTX_CURRENT_MENU_SENDER_CB_NAME: "_send_daily_times_menu",
            })
            assert await handlers.handle_input_value(update, context) == CFG_DAILY_TIMES_MENU
            after = await SettingsService(db).get(CHAT)
            assert after.revision == saved.revision + 1  # One commit, no second overwrite.
            assert after.values["daily_quiz"]["times_msk"] == [{"hour": 9, "minute": 0}, {"hour": 18, "minute": 5}]
            handlers._safe_reschedule_job_for_chat.assert_awaited_once_with(CHAT)
            handlers._update_config_message.assert_not_awaited()
            await SettingsService(db).patch_paths(CHAT, [(["daily_quiz", "times_msk"], [{"hour": 9, "minute": 0}])])
            query = SimpleNamespace(answer=AsyncMock(), data=f"{CB_ADM_DAILY_TIME_REMOVE}:0", from_user=None)
            before = await SettingsService(db).get(CHAT)
            assert await handlers.handle_daily_times_menu_callbacks(SimpleNamespace(callback_query=query), context) == CFG_DAILY_TIMES_MENU
            assert await SettingsService(db).get(CHAT) == before
            assert "Сначала отключите" in query.answer.call_args.args[0]
    asyncio.run(run())


def test_invalid_imported_chat_is_isolated_and_callback_db_outage_fails_closed(pg_env, monkeypatch):
    async def run():
        async with scenario(pg_env) as db:
            await seed(db)
            await seed(db, OTHER_CHAT)
            sync = workers(db)
            await sync.run_once()
            job = next(j for j in sync.daily.application.job_queue.jobs() if j.data["chat_id"] == CHAT)
            token = next(j for j in sync.wisdom.scheduler.get_jobs() if j.args == (str(CHAT),)).kwargs["schedule_token"]
            with monkeypatch.context() as patch:
                patch.setattr("storage.schedule_source.ScheduleSource.read", AsyncMock(side_effect=RuntimeError("offline")))
                with pytest.raises(RuntimeError, match="offline"):
                    await sync.daily._trigger_daily_quiz_job(SimpleNamespace(job=job))
                await sync.wisdom._send_daily_wisdom(str(CHAT), schedule_token=token)
            sync.daily.quiz_manager._initiate_quiz_session.assert_not_awaited()
            sync.wisdom.application.bot.send_message.assert_not_awaited()
            # Legacy/imported malformed settings bypass the new write validation.
            broken = deepcopy(DEFAULTS)
            broken["daily_quiz"].update(enabled=True, timezone="Not/AZone")
            async with db.transaction() as session:
                await session.execute(update(Chat).where(Chat.id == CHAT).values(settings=broken))
            status = await sync.run_once()
            assert status["failed_chats"] == {str(CHAT): "ValueError"}
            assert str(OTHER_CHAT) in status["applied_revisions"]
    asyncio.run(run())


def test_admin_schedule_patch_preserves_siblings_and_reports_worker_revision(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            saved = await seed(db)
            async with db.transaction() as session:
                await session.execute(delete(SystemState).where(SystemState.key == "schedule_sync_status"))
            app = FastAPI()
            install_postgres_admin(app)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                    assert not (await client.get("/api/schedules/status")).json()["fresh"]
                    path = f"/api/chats/{CHAT}/settings"
                    result = await client.put(path, params={"expected_revision": saved.revision}, json={
                        "daily_quiz": {"timezone": "Europe/Berlin"}, "daily_wisdom": {"time": "11:15"}})
                    assert result.status_code == 200, result.text
                    payload = result.json()
                    assert payload["schedule_sync"] == "pending"
                    assert payload["settings"]["daily_quiz"]["times_msk"] == DEFAULTS["daily_quiz"]["times_msk"]
                    assert payload["settings"]["daily_wisdom"]["enabled"]
                    assert payload["revision"] == saved.revision + 1
                    assert (await client.put(path, params={"expected_revision": saved.revision},
                        json={"daily_quiz": {"enabled": False}})).status_code == 409
                    for invalid in ({"daily_quiz": {}}, {"daily_quiz": {"enabled": "false"}},
                                    {"daily_quiz": {"times_msk": []}}, {"daily_wisdom": {"time": "25:00"}},
                                    {"daily_quiz": {"timezone": "Not/AZone"}}):
                        assert (await client.put(path, params={"expected_revision": payload["revision"]}, json=invalid)).status_code == 422
                    assert (await SettingsService(db).get(CHAT)).revision == payload["revision"]
                    async with db.transaction() as session:
                        schedules = (await session.scalars(select(DailySchedule).where(DailySchedule.chat_id == CHAT))).all()
                        assert all(s.timezone == "Europe/Berlin" for s in schedules)
                        assert next(s for s in schedules if s.kind == "wisdom").run_times == ["11:15"]
                    sync = workers(db)
                    await sync.run_once()
                    status = (await client.get("/api/schedules/status")).json()
                    assert status["fresh"]
                    assert status["worker_status"]["applied_revisions"][str(CHAT)] == payload["revision"]
                    expired = dict(status["worker_status"], checked_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
                    async with db.transaction() as session:
                        await OperationalRepository(session).upsert_system_state("schedule_sync_status", expired)
                    assert not (await client.get("/api/schedules/status")).json()["fresh"]
    asyncio.run(run())
