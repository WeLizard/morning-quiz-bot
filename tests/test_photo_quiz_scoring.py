import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from modules.photo_quiz_manager import PhotoQuizManager, PhotoQuizState
from modules.score_manager import ScoreManager


def photo_manager(monkeypatch, award):
    manager = PhotoQuizManager.__new__(PhotoQuizManager)
    manager.score_manager = SimpleNamespace(award_photo_answer=award)
    state = PhotoQuizState(
        chat_id=-123, user_id=456, questions=[{"display_answer": "Сова"}],
        current_question_index=1, start_time=datetime.now(),
        hint_schedule=[30], attempts=1,
    )
    manager.active_photo_quizzes = {-123: state}
    manager._send_final_results = AsyncMock()
    manager._schedule_photo_quiz_cleanup = AsyncMock()
    send = AsyncMock(return_value=SimpleNamespace(message_id=789))
    monkeypatch.setattr("modules.telegram_utils.safe_send_message", send)
    return manager, state, send


def test_photo_finish_is_not_processed_twice(monkeypatch):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        async def award(*args):
            entered.set()
            await release.wait()
            return True

        award_mock = AsyncMock(side_effect=award)
        manager, state, send = photo_manager(monkeypatch, award_mock)
        context = SimpleNamespace(bot=None)
        task = asyncio.create_task(manager._end_photo_quiz(-123, context, correct=True))
        await asyncio.wait_for(entered.wait(), 2)
        await manager._end_photo_quiz(-123, context, correct=True)
        release.set()
        await asyncio.wait_for(task, 2)
        award_mock.assert_awaited_once_with(-123, 456, f"photo:{state.session_id}:0", 5.5)
        assert state.total_score == 5.5 and state.total_correct_answers == 1
        send.assert_awaited_once()
        manager._send_final_results.assert_awaited_once()
    asyncio.run(run())


def test_photo_storage_failure_keeps_question_retryable_and_deadline(monkeypatch):
    async def run():
        award = AsyncMock(side_effect=RuntimeError("database unavailable"))
        manager, state, send = photo_manager(monkeypatch, award)
        context = SimpleNamespace(bot=None)
        await manager._end_photo_quiz(-123, context, correct=True)
        try:
            assert state.is_active
            assert state.total_score == 0 and state.total_correct_answers == 0
            assert state.timer_task is not None and not state.timer_task.done()
            send.assert_not_awaited()
            failed_id = award.call_args.args[2]
            award.side_effect = None
            award.return_value = True
            await manager._end_photo_quiz(-123, context, correct=True)
            assert award.call_args.args[2] == failed_id
            assert state.total_score == 5.5
            send.assert_awaited_once()
        finally:
            state.timer_task.cancel()
            await asyncio.gather(state.timer_task, return_exceptions=True)
    asyncio.run(run())


def test_photo_timeout_does_not_award_score(monkeypatch):
    async def run():
        award = AsyncMock()
        manager, state, send = photo_manager(monkeypatch, award)
        await manager._end_photo_quiz(-123, SimpleNamespace(bot=None), timeout=True)
        award.assert_not_awaited()
        assert state.total_score == 0
        send.assert_awaited_once()
    asyncio.run(run())


def test_json_photo_scoring_remains_supported():
    async def run():
        state = SimpleNamespace(user_scores={})
        data_manager = SimpleNamespace(postgres_storage=None, save_user_data=Mock())
        manager = ScoreManager(SimpleNamespace(), state, data_manager)
        assert await manager.award_photo_answer(-123, 456, "photo:test:0", 5.5)
        user = state.user_scores[-123]["456"]
        assert user["score"] == 5.5 and user["correct_answers_count"] == 1
        assert user["answered_polls"] == set()
        data_manager.save_user_data.assert_called_once_with(-123)
    asyncio.run(run())
