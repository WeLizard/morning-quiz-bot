import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from telegram import User as TelegramUser
from telegram.error import TimedOut
from telegram.ext import JobQueue

from tests.test_postgres_members import CHAT, OTHER_CHAT, USER, pg_env, scenario
from tests.test_postgres_reads_settings import data_manager
from handlers.quiz_manager import QuizManager
from handlers.poll_answer_handler import CustomPollAnswerHandler
from modules.quiz_engine import QuizEngine
from state import BotState, QuizState
from storage.classic_sessions import ClassicSessions, ClassicSessionConflict
from storage.cleanup import CleanupQueue
from storage.members import MemberService
from storage.models import ChatMember, Game, MessageCleanupItem, QuizSession
from storage.repositories import OperationalRepository


def manager(db):
    result = QuizManager.__new__(QuizManager)
    result.data_manager = data_manager(db)
    result.app_config = SimpleNamespace(job_grace_period_seconds=2)
    result.state = BotState(result.app_config)
    result.data_manager.state = result.state
    result.application = SimpleNamespace(job_queue=JobQueue(), bot=SimpleNamespace(send_message=AsyncMock()), bot_data={})
    result._send_question_locks = {}
    result.quiz_engine = SimpleNamespace(send_quiz_poll=AsyncMock())
    return result


async def game(db, chat_id=CHAT, *, phase="active"):
    live = manager(db)
    quiz = QuizState(chat_id, "session", "serial_interval", [{"question": "q1"}, {"question": "q2"}], 2, 60,
                     interval_seconds=30)
    quiz.current_question_index = 1
    quiz.storage_phase = phase
    quiz.active_poll_ids_in_session = {"durable-poll"}
    quiz.latest_poll_id_sent = "durable-poll"
    quiz.next_question_at = (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat()
    live.state.add_active_quiz(chat_id, quiz)
    live.state.add_current_poll("durable-poll", {"chat_id": chat_id, "message_id": 10,
        "correct_option_index": 1, "question_session_index": 0, "question_details": {"question": "q1"},
        "quiz_type": "session", "session_id": quiz.session_id,
        "open_timestamp": datetime.now(timezone.utc).timestamp(),
        "end_timestamp": (datetime.now(timezone.utc) + timedelta(seconds=60)).timestamp()})
    await live._checkpoint_classic(quiz, create=True)
    return live, quiz


def test_classic_checkpoints_are_scoped_and_cannot_revive_finished_or_replaced_game(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            one, quiz = await game(db)
            two, other = await game(db, OTHER_CHAT)
            old = one._classic_snapshot(quiz)
            await one._checkpoint_classic(quiz, status="completed")
            with pytest.raises(ClassicSessionConflict):
                await ClassicSessions(db).save(old)
            assert {s[1]["chat_id"] for s in await ClassicSessions(db).active()} == {OTHER_CHAT}
            replacement, newer = await game(db)
            assert newer.session_id != quiz.session_id
            with pytest.raises(ClassicSessionConflict):
                await ClassicSessions(db).save(old)
            assert len(await ClassicSessions(db).active()) == 2
    asyncio.run(run())


def test_restart_restores_poll_ids_correct_options_and_absolute_deadlines_without_sending(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            live, quiz = await game(db)
            restored = manager(db)
            await restored.restore_all_active_quizzes()
            recovered = restored.state.get_active_quiz(CHAT)
            assert recovered.session_id == quiz.session_id and recovered.current_question_index == 1
            assert restored.state.current_polls["durable-poll"]["correct_option_index"] == 1
            jobs = restored.application.job_queue.jobs()
            assert len(jobs) == 2
            ends = next(j for j in jobs if "ended_poll_id" in j.data)
            next_q = next(j for j in jobs if "expected_q_index_at_trigger" in j.data)
            assert abs(ends.job.trigger.run_date.timestamp() - quiz.poll_history["durable-poll"]["end_timestamp"] - 2) < .01
            assert next_q.job.trigger.run_date.isoformat() == quiz.next_question_at
            restored.quiz_engine.send_quiz_poll.assert_not_awaited()
            restored.application.bot.send_message.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("phase,stopping", [("sending", False), ("active", True)])
def test_uncertain_send_or_stop_does_not_resume_and_queues_known_messages(pg_env, phase, stopping):
    async def run():
        async with scenario(pg_env) as db:
            live, quiz = await game(db, phase=phase)
            quiz.is_stopping = stopping
            await live._checkpoint_classic(quiz)
            restored = manager(db)
            await restored.restore_all_active_quizzes()
            assert not restored.state.active_quizzes
            assert not restored.application.job_queue.jobs()
            async with db.transaction() as session:
                row = await session.scalar(select(Game).where(
                    Game.chat_id == CHAT, Game.mode == 'classic', Game.is_current.is_(True)
                ))
                assert row.status == "interrupted"
                assert (await session.get(MessageCleanupItem, (CHAT, 10))).payload["state"] == "pending"
    asyncio.run(run())


def test_legacy_incomplete_snapshot_is_interrupted_without_removing_data(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            legacy = {"chat_id": CHAT, "questions": [], "scores": {"keep": 15}}
            async with db.transaction() as session:
                repo = OperationalRepository(session)
                await repo.ensure_chat({"id": CHAT, "type": "unknown"})
                await repo.upsert_quiz_session({"id": f"legacy:{CHAT}", "chat_id": CHAT,
                    "kind": "classic", "status": "active", "state": legacy})
            await manager(db).restore_all_active_quizzes()
            async with db.transaction() as session:
                row = await session.get(QuizSession, f"legacy:{CHAT}")
                assert row.status == "interrupted" and row.state == legacy
    asyncio.run(run())


def test_finalization_and_answer_are_serialized_and_scores_rebuilt_from_ledger(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            live, quiz = await game(db)
            entered, release = asyncio.Event(), asyncio.Event()
            async def award(profile):
                entered.set()
                await release.wait()
                profile["score"] += 1
                profile["answered_polls"].add("durable-poll")
                profile["correct_answers_count"] += 1
            task = asyncio.create_task(MemberService(db).apply_answer(chat_id=CHAT, user_id=USER,
                display_name="Test", answer_id="durable-poll", is_correct=True, transition=award,
                classic_session_id=quiz.session_id))
            await asyncio.wait_for(entered.wait(), 2)
            closing = asyncio.create_task(live._checkpoint_classic(quiz, status="completed"))
            await asyncio.sleep(0)
            assert not closing.done()
            release.set()
            await asyncio.wait_for(asyncio.gather(task, closing), 3)
            scores = await ClassicSessions(db).scores(CHAT, ["durable-poll"])
            assert scores[str(USER)]["score"] == 1 and scores[str(USER)]["answered_this_session"] == {"durable-poll"}
            with pytest.raises(ClassicSessionConflict):
                await MemberService(db).apply_answer(chat_id=CHAT, user_id=USER, display_name="Test",
                    answer_id="durable-poll", is_correct=True, transition=award, classic_session_id=quiz.session_id)
    asyncio.run(run())


def test_close_and_cleanup_are_one_transaction(pg_env, monkeypatch):
    async def run():
        async with scenario(pg_env) as db:
            live, quiz = await game(db)
            with monkeypatch.context() as patch:
                patch.setattr(CleanupQueue, "enqueue_in", AsyncMock(side_effect=RuntimeError("queue unavailable")))
                with pytest.raises(RuntimeError):
                    await live._finalize_quiz_session(SimpleNamespace(bot=None), CHAT)
            assert live.state.get_active_quiz(CHAT) is quiz
            async with db.transaction() as session:
                row = await session.scalar(select(Game).where(
                    Game.chat_id == CHAT, Game.mode == 'classic', Game.is_current.is_(True)
                ))
                assert row.status == "active"
    asyncio.run(run())


def test_old_job_token_cannot_advance_new_game(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            live, quiz = await game(db)
            live._send_next_question = AsyncMock()
            ctx = SimpleNamespace(job=SimpleNamespace(name="old", data={"chat_id": CHAT,
                "expected_q_index_at_trigger": 1, "session_id": "old-game"}))
            await live._trigger_next_question_job_after_interval(ctx)
            live._send_next_question.assert_not_awaited()
    asyncio.run(run())


def test_send_pipeline_saves_intent_then_poll_before_jobs(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            live, quiz = await game(db)
            async def send(context, chat_id, question, **kwargs):
                saved = (await ClassicSessions(db).active())[0][1]
                assert saved["storage_phase"] == "sending" and saved["current_question_index"] == 1
                live.state.add_current_poll("next-poll", {"chat_id": chat_id, "message_id": 11,
                    "open_timestamp": datetime.now(timezone.utc).timestamp(), "correct_option_index": 0,
                    "question_session_index": 1, "question_details": question})
                await kwargs["persist_poll"]("next-poll")
                return "next-poll"
            live.quiz_engine.send_quiz_poll.side_effect = send
            await live._send_next_question(SimpleNamespace(bot=None), CHAT)
            saved = (await ClassicSessions(db).active())[0][1]
            assert saved["storage_phase"] == "active" and saved["current_question_index"] == 2
            assert set(saved["polls"]) == {"durable-poll", "next-poll"}
            assert saved["polls"]["next-poll"]["correct_option_index"] == 0
    asyncio.run(run())


def test_uncertain_poll_send_is_not_retried():
    async def run():
        engine = QuizEngine.__new__(QuizEngine)
        engine.app_config = SimpleNamespace(max_poll_question_length=300)
        engine.data_manager = SimpleNamespace(postgres_storage=True, _sanitize_text_for_telegram=lambda text: text)
        engine.rate_limiter = SimpleNamespace(acquire=AsyncMock())
        ctx = SimpleNamespace(bot=SimpleNamespace(send_poll=AsyncMock(side_effect=TimedOut())))
        question = {"question": "q", "options": ["a", "b"], "correct_option_text": "a"}
        assert await engine.send_quiz_poll(ctx, CHAT, question, "Quiz", 30, "session") is None
        ctx.bot.send_poll.assert_awaited_once()
    asyncio.run(run())


def test_new_poll_identity_and_solution_intent_survive_postgres_restart(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            live, quiz = await game(db)
            poll = live.state.current_polls['durable-poll']
            poll.update(option_count=2, option_persistent_ids=['stable-a', 'stable-b'])
            poll['question_details']['explanation'] = 'Explanation after the deadline'
            engine = QuizEngine(live.state, live.app_config, live.data_manager)
            async def cancelled_send(**kwargs):
                # Simulate process cancellation after a request starts. The durable
                # intent has already been written; there is no response/message ID.
                raise asyncio.CancelledError()
            ctx = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock(side_effect=cancelled_send)))
            with pytest.raises(asyncio.CancelledError):
                await engine.send_solution_if_available(ctx, CHAT, 'durable-poll',
                    persist_solution=lambda: live._checkpoint_classic(quiz))
            saved = (await ClassicSessions(db).active())[0][1]['polls']['durable-poll']
            assert saved['solution_delivery'] == 'sending'
            assert saved['option_persistent_ids'] == ['stable-a', 'stable-b']
            restored = manager(db)
            await restored.restore_all_active_quizzes()
            restored_engine = QuizEngine(restored.state, restored.app_config, restored.data_manager)
            assert await restored_engine.send_solution_if_available(ctx, CHAT, 'durable-poll') is None
            ctx.bot.send_message.assert_awaited_once()
            assert restored.state.current_polls['durable-poll']['option_persistent_ids'] == ['stable-a', 'stable-b']
    asyncio.run(run())


def test_solution_ack_is_checkpointed_and_registered_for_cleanup(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            live, quiz = await game(db)
            live.state.current_polls['durable-poll']['question_details']['explanation'] = '2 + 2 = 4!'
            live.quiz_engine = QuizEngine(live.state, live.app_config, live.data_manager)
            live._send_next_question = AsyncMock()
            bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=12)))
            ctx = SimpleNamespace(bot=bot, job=SimpleNamespace(name='end', data={
                'chat_id': CHAT, 'ended_poll_id': 'durable-poll', 'session_id': quiz.session_id}))
            await live._handle_poll_end_job(ctx)
            saved = (await ClassicSessions(db).active())[0][1]['polls']['durable-poll']
            assert saved['solution_sent'] and saved['solution_message_id'] == 12
            bot.send_message.assert_awaited_once_with(chat_id=CHAT, text='💡 2 + 2 = 4!', parse_mode=None)
            await live._checkpoint_classic(quiz, status='completed')
            assert {row[1] for row in await CleanupQueue(db).due(
                now=datetime.now(timezone.utc) + timedelta(minutes=4))} == {10, 12}
    asyncio.run(run())


def test_poll_answer_cache_is_populated_only_after_storage_succeeds(monkeypatch):
    # This unit test isolates retry caching; access/real DB gates are exercised
    # separately by test_admin_actions.py.
    monkeypatch.setattr('storage.admin_actions.AdminActions.allowed', AsyncMock(return_value=True))
    async def run():
        score = SimpleNamespace(update_score_and_get_motivation=AsyncMock(side_effect=RuntimeError("offline")))
        state = SimpleNamespace(get_current_poll_data=lambda _: {"chat_id": CHAT, "correct_option_index": 1},
                                get_active_quiz=lambda _: SimpleNamespace(is_stopping=False, active_poll_ids_in_session=set()))
        handler = CustomPollAnswerHandler(SimpleNamespace(), state, score,
            SimpleNamespace(postgres_storage=SimpleNamespace(database=None)), None)
        user = TelegramUser(USER, "Test", False)
        update_message = SimpleNamespace(poll_answer=SimpleNamespace(user=user, poll_id="retry", option_ids=[1]))
        with pytest.raises(RuntimeError):
            await handler.handle_poll_answer(update_message, SimpleNamespace())
        assert f"retry_{USER}" not in handler._processed_answers
        score.update_score_and_get_motivation.side_effect = None
        score.update_score_and_get_motivation.return_value = (False, None, None, None)
        await handler.handle_poll_answer(update_message, SimpleNamespace())
        assert f"retry_{USER}" in handler._processed_answers
        assert score.update_score_and_get_motivation.await_count == 2
    asyncio.run(run())


def test_two_waiting_jobs_recheck_question_index_under_send_lock(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            live, quiz = await game(db)
            quiz.questions.append({"question": "q3"})
            quiz.num_questions_to_ask = 3
            entered, release = asyncio.Event(), asyncio.Event()
            async def send(context, chat_id, question, **kwargs):
                entered.set()
                await release.wait()
                live.state.add_current_poll("next", {"chat_id": chat_id, "message_id": 11,
                    "open_timestamp": datetime.now(timezone.utc).timestamp(), "correct_option_index": 0,
                    "question_session_index": 1, "question_details": question})
                await kwargs["persist_poll"]("next")
                return "next"
            live.quiz_engine.send_quiz_poll.side_effect = send
            ctx = SimpleNamespace(job=SimpleNamespace(name="next-job", data={"chat_id": CHAT,
                "session_id": quiz.session_id, "expected_q_index_at_trigger": 1}))
            one = asyncio.create_task(live._trigger_next_question_job_after_interval(ctx))
            await asyncio.wait_for(entered.wait(), 2)
            two = asyncio.create_task(live._trigger_next_question_job_after_interval(ctx))
            await asyncio.sleep(0)
            release.set()
            await asyncio.wait_for(asyncio.gather(one, two), 3)
            live.quiz_engine.send_quiz_poll.assert_awaited_once()
            assert quiz.current_question_index == 2
    asyncio.run(run())


def test_timeout_and_answer_of_older_poll_do_not_advance_current_question(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            live, quiz = await game(db)
            quiz.latest_poll_id_sent = "newer"
            live._send_next_question = AsyncMock()
            live.quiz_engine.send_solution_if_available = AsyncMock(return_value=12)
            await live._handle_early_answer_for_session(SimpleNamespace(), CHAT, "durable-poll")
            assert not quiz.progression_triggered_for_poll
            ctx = SimpleNamespace(job=SimpleNamespace(name="old-end", data={"chat_id": CHAT,
                "session_id": quiz.session_id, "ended_poll_id": "durable-poll"}))
            await live._handle_poll_end_job(ctx)
            live._send_next_question.assert_not_awaited()
            saved = (await ClassicSessions(db).active())[0][1]
            assert not saved["active_poll_ids_in_session"]
            await live._checkpoint_classic(quiz, status="completed")
            assert {row[1] for row in await CleanupQueue(db).due(now=datetime.now(timezone.utc) + timedelta(minutes=4))} == {10, 12}
    asyncio.run(run())


def test_finalization_waits_for_inflight_poll_checkpoint(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            live, quiz = await game(db)
            lock = asyncio.Lock()
            live._send_question_locks[CHAT] = lock
            async with lock:
                async def close(*args):
                    await live._checkpoint_classic(quiz, status="stopped")
                live._finalize_quiz_session_impl = AsyncMock(side_effect=close)
                closing = asyncio.create_task(live._finalize_quiz_session(SimpleNamespace(), CHAT, was_stopped=True))
                await asyncio.sleep(0)
                live._finalize_quiz_session_impl.assert_not_awaited()
                live.state.add_current_poll("next", {"chat_id": CHAT, "message_id": 11,
                    "open_timestamp": datetime.now(timezone.utc).timestamp(), "correct_option_index": 0})
                await live._confirm_classic_poll(quiz, "next")
            await asyncio.wait_for(closing, 3)
            async with db.transaction() as session:
                row = await session.scalar(select(Game).where(
                    Game.chat_id == CHAT, Game.mode == 'classic', Game.is_current.is_(True)
                ))
                assert row.status == "stopped"
                assert (await session.get(MessageCleanupItem, (CHAT, 11))).payload["state"] == "pending"
    asyncio.run(run())


def test_full_finalization_enqueues_results_without_legacy_cleanup_job(pg_env, monkeypatch):
    async def run():
        async with scenario(pg_env) as db:
            live, quiz = await game(db)
            live.app_config.default_chat_settings = {"auto_delete_bot_messages": True}
            live.score_manager = SimpleNamespace(get_session_profiles=AsyncMock(return_value={}),
                format_scores=lambda **kwargs: "Done")
            with monkeypatch.context() as patch:
                sender = AsyncMock(return_value=SimpleNamespace(message_id=300))
                patch.setattr("handlers.quiz_manager.safe_send_message", sender)
                await live._finalize_quiz_session(SimpleNamespace(bot=None), CHAT)
            assert live.state.get_active_quiz(CHAT) is None
            assert not live.application.job_queue.jobs()
            async with db.transaction() as session:
                assert (await session.get(MessageCleanupItem, (CHAT, 300))).payload["state"] == "pending"
    asyncio.run(run())


def test_restart_rebuilds_session_score_from_committed_answers_not_memory(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            live, quiz = await game(db)
            async def award(profile):
                profile["score"] += 1
                profile["answered_polls"].add("durable-poll")
                profile["correct_answers_count"] += 1
            await MemberService(db).apply_answer(chat_id=CHAT, user_id=USER,
                display_name="Test", answer_id="durable-poll", is_correct=True, transition=award,
                classic_session_id=quiz.session_id)
            assert quiz.scores == {}  # Simulate a crash before publishing into BotState.
            restored = manager(db)
            await restored.restore_all_active_quizzes()
            score = restored.state.get_active_quiz(CHAT).scores[str(USER)]
            assert score["score"] == 1 and score["answered_this_session"] == {"durable-poll"}
    asyncio.run(run())


def test_expired_poll_cannot_award_points(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            live, quiz = await game(db)
            live.state.current_polls["durable-poll"]["end_timestamp"] = datetime.now(timezone.utc).timestamp() - 1
            await live._checkpoint_classic(quiz)
            transition = AsyncMock()
            with pytest.raises(ClassicSessionConflict):
                await MemberService(db).apply_answer(chat_id=CHAT, user_id=USER, display_name="Test",
                    answer_id="durable-poll", is_correct=True, transition=transition, classic_session_id=quiz.session_id)
            transition.assert_not_awaited()
            assert await ClassicSessions(db).scores(CHAT, ["durable-poll"]) == {}
    asyncio.run(run())
