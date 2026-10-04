"""Photo catalog and crash boundaries, isolated PostgreSQL, mocked Telegram."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import delete, func, select, update

from tests.test_postgres_members import CHAT, USER, pg_env, scenario, scorer
from modules.photo_quiz_manager import PhotoQuizManager, PhotoQuizState
from storage.models import ChatMember, Game, PhotoQuizItem, PollAnswer, QuizSession, User
from storage.photos import PhotoCatalog, PhotoSessionConflict, PhotoSessions
from storage.runtime import PostgresRuntimeStorage


def payload():
    state = PhotoQuizState(CHAT, USER, [{"display_answer": "Сова", "normalized_answer": "сова",
        "image_path": "unused.webp", "masks": {"initial": "___", "first_letters": "С__", "partial": "Со_"}}],
        start_time=datetime.now(timezone.utc), current_question_index=1, hints_enabled=False,
        phase="active", time_limit=60, hint_schedule=[20, 40])
    return PhotoQuizManager._record(state)


def manager(db, tmp_path):
    result = PhotoQuizManager(SimpleNamespace(postgres_storage=PostgresRuntimeStorage(db)), scorer(db))
    result.images_dir = tmp_path
    result.metadata_file = tmp_path / "must-not-exist.json"
    result._schedule_photo_quiz_cleanup = AsyncMock()
    return result


def context():
    return SimpleNamespace(bot=SimpleNamespace(send_photo=AsyncMock(return_value=SimpleNamespace(message_id=10)),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=20))), bot_data={}, job_queue=None)


async def prepare(manager, context, monkeypatch):
    (manager.images_dir / "Сова.webp").write_bytes(b"fixture-not-a-real-image")
    await PhotoCatalog(manager.postgres_storage.database).get_or_create("Сова")
    monkeypatch.setattr("modules.telegram_utils.safe_send_message", AsyncMock(return_value=SimpleNamespace(message_id=30)))
    assert await manager.start_photo_quiz_series(context, CHAT, USER, 60, 1, False)
    return manager.active_photo_quizzes[CHAT]


def test_catalog_create_never_overwrites_admin_metadata(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            catalog = PhotoCatalog(db)
            key = "test-photo-catalog"
            try:
                await asyncio.gather(catalog.get_or_create(key), catalog.get_or_create(key))
                async with db.transaction() as session:
                    await session.execute(update(PhotoQuizItem).where(PhotoQuizItem.media_key == key).values(
                        correct_answer="Edited", enabled=False, metadata_json={"display_answer": "Display", "custom": 7}))
                read = await catalog.get_or_create(key)
                assert read["correct_answer"] == "Edited" and read["custom"] == 7
                assert read["display_answer"] == "Display" and not read["enabled"]
                assert (await catalog.load())[key] == read
            finally:
                async with db.transaction() as session:
                    await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key == key))
    asyncio.run(run())


def test_only_one_series_per_chat_and_stale_uuid_cannot_change_replacement(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            service = PhotoSessions(db)
            candidates = [payload(), payload()]
            results = await asyncio.gather(*(service.create(p) for p in candidates), return_exceptions=True)
            assert sum(isinstance(r, PhotoSessionConflict) for r in results) == 1
            saved = next(r for r in results if isinstance(r, dict))
            await service.save(saved, status="stopped")
            newer = await service.create(payload())
            with pytest.raises(PhotoSessionConflict):
                await service.complete_question(saved, correct=True, points=6)
            assert (await service.active())[0] == newer
    asyncio.run(run())


def test_photo_completion_atomically_updates_series_and_score_once(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            service = PhotoSessions(db)
            saved = await service.create(payload())
            results = await asyncio.gather(*(service.complete_question(saved, correct=True, points=5.5) for _ in range(2)))
            assert results[0] == results[1]
            assert results[0]["phase"] == "between"
            assert results[0]["total_score"] == 5.5 and results[0]["total_correct_answers"] == 1
            async with db.transaction() as session:
                member = await session.get(ChatMember, (CHAT, USER))
                assert member.score == Decimal("5.5") and member.answered_count == 0
                assert (await session.get(User, USER)).global_score == Decimal("5.5")
                assert await session.scalar(select(func.count()).select_from(PollAnswer).where(PollAnswer.chat_id == CHAT)) == 1
                row = await session.scalar(select(Game).where(
                    Game.chat_id == CHAT, Game.mode == 'photo', Game.is_current.is_(True)))
                assert row.state == results[0]
    asyncio.run(run())


def test_photo_session_save_failure_rolls_back_ledger_profile_and_progress(pg_env, monkeypatch):
    async def run():
        async with scenario(pg_env) as db:
            service = PhotoSessions(db)
            saved = await service.create(payload())
            with monkeypatch.context() as patch:
                patch.setattr(PhotoSessions, "_write", Mock(side_effect=RuntimeError("session write failed")))
                with pytest.raises(RuntimeError):
                    await service.complete_question(saved, correct=True, points=6)
            async with db.transaction() as session:
                assert await session.get(ChatMember, (CHAT, USER)) is None
                assert await session.scalar(select(func.count()).select_from(PollAnswer).where(PollAnswer.chat_id == CHAT)) == 0
            assert (await service.active())[0] == saved
            assert (await service.complete_question(saved, correct=True, points=6))["total_score"] == 6
    asyncio.run(run())


def test_manager_restarts_without_resending_or_resetting_deadline(pg_env, tmp_path, monkeypatch):
    async def run():
        async with scenario(pg_env) as db:
            first, ctx = manager(db, tmp_path), context()
            state = await prepare(first, ctx, monkeypatch)
            started, session_id = state.start_time, state.session_id
            state.attempts = 2
            await first._persist(state)
            await first.shutdown()
            second = manager(db, tmp_path)
            try:
                await second.restore_sessions(ctx)
                restored = second.active_photo_quizzes[CHAT]
                assert restored.start_time == started and restored.session_id == session_id
                assert restored.attempts == 2 and restored.current_question_index == 1
                ctx.bot.send_photo.assert_awaited_once()
                await second._end_photo_quiz(CHAT, ctx, correct=True)
                async with db.transaction() as session:
                    assert (await session.get(ChatMember, (CHAT, USER))).score == Decimal(4)
                    row = await session.scalar(select(Game).where(
                        Game.chat_id == CHAT, Game.mode == 'photo', Game.is_current.is_(True)))
                    assert row.status == "finished"
                assert not second.active_photo_quizzes
                assert not second.metadata_file.exists()
            finally:
                await second.shutdown()
                async with db.transaction() as session:
                    await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key == "Сова"))
    asyncio.run(run())


def test_unacknowledged_send_is_interrupted_never_repeated(pg_env, tmp_path):
    async def run():
        async with scenario(pg_env) as db:
            saved = payload()
            saved.update(phase="sending", is_active=False, current_question_index=0, total_score=5)
            await PhotoSessions(db).create(saved)
            restored, ctx = manager(db, tmp_path), context()
            await restored.restore_sessions(ctx)
            ctx.bot.send_photo.assert_not_awaited()
            assert not restored.active_photo_quizzes
            async with db.transaction() as session:
                row = await session.scalar(select(Game).where(
                    Game.chat_id == CHAT, Game.mode == 'photo', Game.is_current.is_(True)))
                assert row.status == "interrupted" and row.state["total_score"] == 5
    asyncio.run(run())


def test_expired_question_restores_as_timeout_without_award(pg_env, tmp_path, monkeypatch):
    async def run():
        async with scenario(pg_env) as db:
            saved = payload()
            saved["start_time"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
            await PhotoSessions(db).create(saved)
            restored, ctx = manager(db, tmp_path), context()
            monkeypatch.setattr("modules.telegram_utils.safe_send_message", AsyncMock(return_value=SimpleNamespace(message_id=30)))
            await restored.restore_sessions(ctx)
            ctx.bot.send_photo.assert_not_awaited()
            assert not restored.active_photo_quizzes
            async with db.transaction() as session:
                assert await session.get(ChatMember, (CHAT, USER)) is None
                row = await session.scalar(select(Game).where(
                    Game.chat_id == CHAT, Game.mode == 'photo', Game.is_current.is_(True)))
                assert row.status == "finished"
    asyncio.run(run())


def test_uncertain_commit_retry_preserves_points_and_progress(pg_env, tmp_path, monkeypatch):
    async def run():
        async with scenario(pg_env) as db:
            live, ctx = manager(db, tmp_path), context()
            state = await prepare(live, ctx, monkeypatch)
            complete = PhotoSessions.complete_question

            async def fail_after_commit(service, *args, **kwargs):
                await complete(service, *args, **kwargs)
                raise RuntimeError("lost commit acknowledgement")

            try:
                with monkeypatch.context() as patch:
                    patch.setattr(PhotoSessions, "complete_question", fail_after_commit)
                    await live._end_photo_quiz(CHAT, ctx, correct=True)
                assert state.is_active and state.total_score == 0
                await live._end_photo_quiz(CHAT, ctx, timeout=True)
                assert state.total_score == 5 and state.total_correct_answers == 1
                assert state.last_outcome["correct"]  # Lost ACK must not turn a win into a timeout.
                async with db.transaction() as session:
                    assert (await session.get(ChatMember, (CHAT, USER))).score == Decimal(5)
            finally:
                await live.shutdown()
                async with db.transaction() as session:
                    await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key == "Сова"))
    asyncio.run(run())


def test_photo_rows_do_not_enter_classic_restore_and_survive_classic_snapshot(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            saved = await PhotoSessions(db).create(payload())
            runtime = PostgresRuntimeStorage(db)
            assert await runtime.load_into_state(SimpleNamespace(global_settings={})) == {}
            with pytest.raises(RuntimeError, match="snapshots"):
                await runtime.replace_active_quizzes({})
            assert await PhotoSessions(db).active() == [saved]
    asyncio.run(run())


def test_disabled_photo_is_not_selected_and_database_failure_has_no_json_fallback(pg_env, tmp_path, monkeypatch):
    async def run():
        async with scenario(pg_env) as db:
            live, ctx = manager(db, tmp_path), context()
            live._get_image_groups = Mock(return_value={"test-disabled": ["test-disabled"]})
            live._load_images_metadata = Mock(side_effect=AssertionError("no JSON"))
            try:
                await PhotoCatalog(db).get_or_create("test-disabled")
                async with db.transaction() as session:
                    await session.execute(update(PhotoQuizItem).where(PhotoQuizItem.media_key == "test-disabled").values(enabled=False))
                assert not await live.start_photo_quiz_series(ctx, CHAT, USER, 60, 1, False)
                with monkeypatch.context() as patch:
                    patch.setattr(PhotoCatalog, "load", AsyncMock(side_effect=RuntimeError("offline")))
                    assert not await live.start_photo_quiz_series(ctx, CHAT, USER, 60, 1, False)
                ctx.bot.send_photo.assert_not_awaited()
                live._load_images_metadata.assert_not_called()
                with pytest.raises(RuntimeError):
                    live._save_images_metadata()
            finally:
                async with db.transaction() as session:
                    await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key == "test-disabled"))
    asyncio.run(run())


def test_wrong_attempt_and_hints_are_persisted_and_late_answer_cannot_score(pg_env, tmp_path, monkeypatch):
    async def run():
        async with scenario(pg_env) as db:
            live, ctx = manager(db, tmp_path), context()
            state = await prepare(live, ctx, monkeypatch)
            message = SimpleNamespace(text="абракадабра", reply_text=AsyncMock())
            update_message = SimpleNamespace(effective_chat=SimpleNamespace(id=CHAT),
                                             effective_user=SimpleNamespace(id=USER), message=message)
            try:
                stranger = SimpleNamespace(effective_chat=SimpleNamespace(id=CHAT),
                    effective_user=SimpleNamespace(id=USER + 1), message=message)
                assert not await live.check_answer(stranger, ctx)
                assert await live.check_answer(update_message, ctx)
                saved = (await PhotoSessions(db).active())[0]
                assert saved["attempts"] == 1
                state.current_hint_level, state.hints_given = 1, ["С___"]
                state.message_ids_to_delete.add(55)
                state.start_time = datetime.now(timezone.utc) - timedelta(minutes=2)
                await live._persist(state)
                message.text = "сова"
                assert await live.check_answer(update_message, ctx)
                async with db.transaction() as session:
                    row = await session.scalar(select(Game).where(
                        Game.chat_id == CHAT, Game.mode == 'photo', Game.is_current.is_(True)))
                    assert row.state["attempts"] == 1 and row.state["current_hint_level"] == 1
                    assert 55 in row.state["message_ids_to_delete"]
                    assert not row.state["last_outcome"]["correct"]
                    assert await session.get(ChatMember, (CHAT, USER)) is None
            finally:
                await live.shutdown()
                async with db.transaction() as session:
                    await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key == "Сова"))
    asyncio.run(run())


def test_concurrent_start_sends_one_photo_and_stop_is_durable(pg_env, tmp_path, monkeypatch):
    async def run():
        async with scenario(pg_env) as db:
            live, ctx = manager(db, tmp_path), context()
            (tmp_path / "Сова.webp").write_bytes(b"fixture")
            await PhotoCatalog(db).get_or_create("Сова")
            try:
                results = await asyncio.gather(*(live.start_photo_quiz_series(ctx, CHAT, USER, 60, 1, False) for _ in range(2)))
                assert sorted(results) == [False, True]
                ctx.bot.send_photo.assert_awaited_once()
                update_message = SimpleNamespace(effective_chat=SimpleNamespace(id=CHAT), message=SimpleNamespace(reply_text=AsyncMock()))
                await live.stop_photo_quiz(update_message, ctx)
                assert not await PhotoSessions(db).active()
                restored = manager(db, tmp_path)
                await restored.restore_sessions(ctx)
                assert not restored.active_photo_quizzes
                ctx.bot.send_photo.assert_awaited_once()
            finally:
                await live.shutdown()
                async with db.transaction() as session:
                    await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key == "Сова"))
    asyncio.run(run())


def test_question_timeout_keeps_retry_task_when_database_is_down(pg_env, tmp_path, monkeypatch):
    async def run():
        async with scenario(pg_env) as db:
            saved = payload()
            saved["start_time"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
            await PhotoSessions(db).create(saved)
            restored, ctx = manager(db, tmp_path), context()
            try:
                with monkeypatch.context() as patch:
                    patch.setattr(PhotoSessions, "complete_question", AsyncMock(side_effect=RuntimeError("offline")))
                    await restored.restore_sessions(ctx)
                    state = restored.active_photo_quizzes[CHAT]
                    assert state.is_active and state.timer_task is not None
                    assert not state.timer_task.done()
                    ctx.bot.send_message.assert_not_awaited()
            finally:
                await restored.shutdown()
    asyncio.run(run())


def test_shared_photo_application_is_idempotent_and_uses_games_only(pg_env, tmp_path, monkeypatch):
    from application.photo import PhotoApplicationService
    from uuid import uuid4

    async def run():
        async with scenario(pg_env) as db:
            monkeypatch.setenv('PHOTO_IMAGES_DIR', str(tmp_path))
            (tmp_path / 'owl.webp').write_bytes(b'RIFF-photo-test-WEBP')
            questions = [
                {'display_answer': 'Сова', 'media': {'media_key': 'owl', 'storage_name': 'owl'}},
                {'display_answer': 'Козалось', 'media': {'media_key': 'owl', 'storage_name': 'owl'}},
            ]
            async with db.transaction() as session:
                started = await PhotoApplicationService(db, session).start(
                    chat_id=CHAT, user_id=USER, display_name='Tester', question_count=2,
                    open_seconds=60, hints_enabled=False, questions=questions,
                    command_id=str(uuid4()), now=1000,
                )
            first = started['question']['round_id']
            command = str(uuid4())
            async with db.transaction() as session:
                service = PhotoApplicationService(db, session)
                wrong = await service.answer(chat_id=CHAT, user_id=USER, display_name='Tester',
                    round_id=first, answer='ворона', command_id=command, now=1001)
                duplicate = await service.answer(chat_id=CHAT, user_id=USER, display_name='Tester',
                    round_id=first, answer='ворона', command_id=command, now=1001)
                assert wrong == duplicate and wrong['verdict'] == 'wrong'
            async with db.transaction() as session:
                won = await PhotoApplicationService(db, session).answer(
                    chat_id=CHAT, user_id=USER, display_name='Tester', round_id=first,
                    answer='СОВА', command_id=str(uuid4()), now=1002)
                second = won['question']['round_id']
            async with db.transaction() as session:
                finished = await PhotoApplicationService(db, session).answer(
                    chat_id=CHAT, user_id=USER, display_name='Tester', round_id=second,
                    answer='козалось', command_id=str(uuid4()), now=1003)
                assert finished['status'] == 'finished' and finished['correct'] == 2
                assert finished['score'] == '9.5'  # one persisted wrong-attempt penalty
                assert await session.scalar(select(func.count()).select_from(QuizSession).where(
                    QuizSession.kind == 'photo')) == 0
                game = await session.scalar(select(Game).where(Game.chat_id == CHAT, Game.mode == 'photo'))
                assert game.state['mode'] == 'photo' and game.status == 'finished'
                answers = await session.scalar(select(func.count()).select_from(PollAnswer).where(
                    PollAnswer.game_id == game.id))
                assert answers == 2
    asyncio.run(run())
