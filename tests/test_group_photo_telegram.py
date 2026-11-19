"""Private group Photo adapter contracts; no live Telegram or database."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
import time

import pytest

from handlers.mafia_handlers import MafiaHandlers
from handlers.photo_quiz_handlers import PhotoQuizHandlers
from modules.mini_app_launch import direct_photo_link


ROUND = 'a' * 32


class Database:
    @asynccontextmanager
    async def transaction(self):
        yield object()


def test_photo_link_scopes_the_private_form_to_one_round(monkeypatch):
    monkeypatch.setenv('MINI_APP_URL', 'https://quiz.example.com/app')
    monkeypatch.setenv('MINI_APP_SHORT_NAME', 'play')
    link = direct_photo_link('quizbot', -1001234567890, ROUND)
    assert link == f'https://t.me/quizbot/play?startapp=photo_n1001234567890_{ROUND}'
    assert len(link.split('startapp=')[1]) <= 64
    for chat, round_id in [(1, ROUND), (True, ROUND), (-123, 'stale'), (-2**52, ROUND)]:
        with pytest.raises(ValueError):
            direct_photo_link('quizbot', chat, round_id)
    monkeypatch.delenv('MINI_APP_URL')
    assert direct_photo_link('quizbot', -123, ROUND) is None


def test_public_group_message_is_never_a_private_answer(monkeypatch):
    import application.photo
    service = SimpleNamespace(current=AsyncMock(return_value={'answer_policy': 'group_private_deadline'}),
                              settle_due=AsyncMock(), answer=AsyncMock())
    monkeypatch.setattr(application.photo, 'PhotoApplicationService', lambda *args: service)
    handlers = PhotoQuizHandlers(SimpleNamespace(postgres_storage=SimpleNamespace(database=Database())))
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=-123, type='group'),
                             effective_user=SimpleNamespace(id=42, is_bot=False),
                             message=SimpleNamespace(text='Сова'))
    assert asyncio.run(handlers.handle_photo_quiz_message(update, SimpleNamespace())) is False
    service.answer.assert_not_awaited()
    service.settle_due.assert_not_awaited()


def test_group_question_has_private_button_and_no_public_answer_instruction(monkeypatch, tmp_path):
    import application.photo
    monkeypatch.setenv('MINI_APP_URL', 'https://quiz.example.com/app')
    monkeypatch.setenv('MINI_APP_SHORT_NAME', 'play')
    path = tmp_path / 'photo.webp'
    path.write_bytes(b'image-placeholder-for-mocked-delivery')
    service = SimpleNamespace(question_delivery=AsyncMock(return_value={
        'closes_at': time.time() + 60, 'chat_id': -123, 'round_id': ROUND,
        'question_number': 1, 'question_count': 3, 'mask': None,
        'image_path': path, 'answer_policy': 'group_private_deadline',
    }))
    monkeypatch.setattr(application.photo, 'PhotoApplicationService', lambda *args: service)
    bot = SimpleNamespace(username='quizbot', send_photo=AsyncMock())
    asyncio.run(MafiaHandlers(Database())._deliver_photo_question(
        SimpleNamespace(bot=bot), {'game_id': 'game', 'payload': {'round_id': ROUND}}))
    sent = bot.send_photo.await_args.kwargs
    assert 'обычным сообщением' not in sent['caption']
    assert 'Чужие ответы и очки скрыты' in sent['caption']
    assert sent['reply_markup'].inline_keyboard[0][0].url.endswith(f'photo_n123_{ROUND}')


def test_closed_group_result_lists_each_solver_without_wrong_answers():
    bot = SimpleNamespace(send_message=AsyncMock())
    asyncio.run(MafiaHandlers(Database())._deliver_photo_text(SimpleNamespace(bot=bot), {
        'kind': 'photo.result', 'chat_id': -123,
        'payload': {'answer': 'Сова', 'solvers': [
            {'name': '<Вера>', 'points': 6}, {'name': 'Пётр', 'points': 5.5},
        ]},
    }))
    text = bot.send_message.await_args.args[1]
    assert '&lt;Вера&gt;: +6' in text and 'Пётр: +5.5' in text
    assert '<b>Сова</b>' in text


def test_group_final_counts_answers_separately_from_questions():
    bot = SimpleNamespace(send_message=AsyncMock())
    asyncio.run(MafiaHandlers(Database())._deliver_photo_text(SimpleNamespace(bot=bot), {
        'kind': 'photo.finished', 'chat_id': -123,
        'payload': {'answer_policy': 'group_private_deadline', 'question_count': 1,
                    'correct': 2, 'score': 12},
    }))
    text = bot.send_message.await_args.args[1]
    assert 'Вопросов в серии: 1' in text and 'Верных ответов участников: 2' in text
    assert '2 из 1' not in text
