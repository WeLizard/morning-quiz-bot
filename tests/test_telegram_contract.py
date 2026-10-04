"""Real PTB serialization with an in-memory transport, never Telegram network IO."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram import PollAnswer, User
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut
from telegram.ext import Defaults, ExtBot
from telegram.request import BaseRequest

import data_manager  # Initialize the existing package in application order.
from handlers.poll_answer_handler import CustomPollAnswerHandler
from modules.quiz_engine import QuizEngine
from modules.quiz_payload import prepare_options, question_with_header, selected_option_index
from modules.telegram_transport import telegram_request
from modules.telegram_utils import (
    ChatNotFoundError, MessageTooLongError, PartialDeliveryError, TelegramMessageError,
    UserBlockedError, is_formatting_error, safe_send_message,
)


class RecordingRequest(BaseRequest):
    def __init__(self):
        self.calls = []

    @property
    def read_timeout(self):
        return 1

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit('/', 1)[-1]
        fields = {}
        for key, value in request_data.json_parameters.items():
            try:
                fields[key] = json.loads(value)
            except json.JSONDecodeError:
                fields[key] = value
        self.calls.append((endpoint, fields))
        if endpoint == 'getMe':
            result = {'id': 123456, 'is_bot': True, 'first_name': 'Local', 'username': 'local_test_bot'}
        elif endpoint == 'sendPoll':
            result = {'message_id': 42, 'date': 1700000000, 'chat': {'id': -1001, 'type': 'supergroup'},
                'poll': {'id': 'sdk-poll', 'question': fields['question'],
                    'options': [{'text': option['text'], 'voter_count': 0, 'persistent_id': f'opt-{index}'}
                                for index, option in enumerate(fields['options'])],
                    'total_voter_count': 0, 'is_closed': False, 'is_anonymous': False,
                    'type': 'quiz', 'allows_multiple_answers': False, 'allows_revoting': False,
                    'members_only': False, 'correct_option_ids': fields['correct_option_ids']}}
        else:
            raise AssertionError(f'Unexpected API method: {endpoint}')
        return 200, json.dumps({'ok': True, 'result': result}).encode()


def engine_for(poll=None, postgres=True):
    polls = {'solution-poll': poll} if poll is not None else {}
    state = SimpleNamespace(current_polls=polls, get_current_poll_data=polls.get,
                            add_current_poll=lambda key, value: polls.__setitem__(key, value))
    engine = QuizEngine(state, SimpleNamespace(), SimpleNamespace(
        postgres_storage=postgres, disable_daily_quiz_for_chat=AsyncMock()))
    engine.rate_limiter = SimpleNamespace(acquire=AsyncMock())
    return engine


def question(text='Какой ответ?'):
    return {'question': text, 'options': ['Да_1!', 'Нет (2)'], 'correct_option_text': 'Да_1!'}


def test_real_sdk_serializes_plain_single_answer_contract():
    async def run():
        request = RecordingRequest()
        engine = engine_for()
        saved = []
        async def persist(poll_id):
            saved.append(deepcopy(engine.state.get_current_poll_data(poll_id)))
        async with ExtBot('123456:LOCAL_TEST_ONLY', request=request,
                          get_updates_request=RecordingRequest(), defaults=Defaults(parse_mode='MarkdownV2')) as bot:
            text = 'Кто сказал: «2 + 2 = 4»? [A_B] (№1)! 🦉'
            poll_id = await engine.send_quiz_poll(SimpleNamespace(bot=bot), -1001, question(text),
                'Вопрос 1/5', 30, 'session', current_category_name='Наука & техника', persist_poll=persist)
        assert poll_id == 'sdk-poll'
        fields = request.calls[-1][1]
        assert fields['question'].endswith(text) and '\\' not in fields['question']
        assert 'question_parse_mode' not in fields and 'explanation' not in fields
        assert 'correct_option_id' not in fields
        assert fields['type'] == 'quiz' and fields['open_period'] == 30
        assert fields['is_anonymous'] is False
        assert fields['allows_multiple_answers'] is False
        assert fields['allows_revoting'] is False and fields['shuffle_options'] is False
        assert all('text_parse_mode' not in option for option in fields['options'])
        index, = fields['correct_option_ids']
        assert fields['options'][index]['text'] == 'Да_1!'
        assert saved[0]['option_persistent_ids'] == ['opt-0', 'opt-1']
        assert saved[0]['options'] == [item['text'] for item in fields['options']]
        assert saved[0]['display_question'] == fields['question']
        answer = PollAnswer.de_json({'poll_id': poll_id, 'user': {'id': 8, 'first_name': 'A', 'is_bot': False},
                                    'option_ids': [index], 'option_persistent_ids': [f'opt-{index}']}, bot)
        assert selected_option_index(answer, saved[0]) == index
    asyncio.run(run())


def test_shuffle_retains_identity_and_full_long_options(monkeypatch):
    monkeypatch.setattr('modules.quiz_payload.random.shuffle', lambda items: items.reverse())
    a, b = 'а' * 99 + '1', 'а' * 99 + '2'
    source = {'question': '🦉 _Q_ (1)?', 'options': [a, b], 'correct_option_text': a}
    original = deepcopy(source)
    text, options, index, correct = prepare_options(source)
    assert (options, index, correct) == ([b, a], 1, a)
    assert source == original and text == source['question']


@pytest.mark.parametrize('change', [
    {'question': 'x' * 301}, {'question': ''}, {'options': ['x' * 101, 'y']},
    {'options': ['x', ' x '], 'correct_option_text': 'x'}, {'correct_option_text': 'absent'},
    {'options': ['a']}, {'options': list('abcdefghijk')},
])
def test_invalid_questions_are_rejected_without_truncation(change):
    with pytest.raises(ValueError):
        prepare_options({**question(), **change})


@pytest.mark.parametrize('length', [1, 280, 299, 300])
def test_full_question_has_priority_over_header(length):
    text = 'Я' * length
    result = question_with_header(text, 'Вопрос 1/10', 'Длинная категория' * 10)
    assert result.endswith(text) and len(result) <= 300


@pytest.mark.parametrize('indices,ids,expected', [
    ([1], ['b'], 1), ([0], ['a'], 0), ([], [], None), ([0, 1], ['a', 'b'], None),
    ([1], ['a'], None), ([9], ['b'], None), ([-1], ['b'], None), ([1], [], None),
])
def test_persistent_vote_identity(indices, ids, expected):
    vote = SimpleNamespace(option_ids=indices, option_persistent_ids=ids)
    assert selected_option_index(vote, {'option_count': 2, 'option_persistent_ids': ['a', 'b']}) == expected


def test_legacy_poll_checkpoint_accepts_index_only_answer():
    assert selected_option_index(SimpleNamespace(option_ids=[1]), {'correct_option_index': 1}) == 1


@pytest.mark.parametrize('operation', ['poll', 'solution'])
def test_429_wait_rechecks_game_access_before_retry(monkeypatch, operation):
    monkeypatch.setattr('modules.telegram_transport.asyncio.sleep', AsyncMock())
    async def run():
        engine = engine_for({'question_details': {'explanation': 'Answer'}})
        allowed = AsyncMock(side_effect=[True, False])
        bot = SimpleNamespace(send_poll=AsyncMock(side_effect=RetryAfter(1)),
                              send_message=AsyncMock(side_effect=RetryAfter(1)))
        context = SimpleNamespace(bot=bot)
        if operation == 'poll':
            assert await engine.send_quiz_poll(context, 1, question(), 'Quiz', 30, 'session', before_send=allowed) is None
            bot.send_poll.assert_awaited_once()
        else:
            assert await engine.send_solution_if_available(context, 1, 'solution-poll', before_send=allowed) is None
            bot.send_message.assert_awaited_once()
        assert allowed.await_count == 2
    asyncio.run(run())


@pytest.mark.parametrize('postgres', [False, True])
@pytest.mark.parametrize('error', [TimedOut(), NetworkError('connection lost'), BadRequest('invalid question')])
def test_poll_is_not_blindly_resent(postgres, error):
    async def run():
        engine = engine_for(postgres=postgres)
        bot = SimpleNamespace(send_poll=AsyncMock(side_effect=error))
        assert await engine.send_quiz_poll(SimpleNamespace(bot=bot), 1, question(), 'Quiz', 30, 'session') is None
        bot.send_poll.assert_awaited_once()
    asyncio.run(run())


@pytest.mark.parametrize('wait', [2, timedelta(seconds=2)])
def test_explicit_429_retries_after_requested_delay(monkeypatch, wait):
    monkeypatch.setenv('PTB_TIMEDELTA', '1' if isinstance(wait, timedelta) else '0')
    sleep = AsyncMock()
    monkeypatch.setattr('modules.telegram_transport.asyncio.sleep', sleep)
    async def run():
        call = AsyncMock(side_effect=[RetryAfter(wait), 'ok'])
        assert await telegram_request(call) == 'ok'
        sleep.assert_awaited_once_with(2.0)
        assert call.await_count == 2
    asyncio.run(run())


@pytest.mark.parametrize('wait,calls,sleeps', [(40, 1, 0), (20, 2, 1), (1, 3, 2)])
def test_429_budget_and_no_sleep_after_last_attempt(monkeypatch, wait, calls, sleeps):
    sleep = AsyncMock()
    monkeypatch.setattr('modules.telegram_transport.asyncio.sleep', sleep)
    async def run():
        call = AsyncMock(side_effect=RetryAfter(wait))
        with pytest.raises(RetryAfter):
            await telegram_request(call)
        assert call.await_count == calls and sleep.await_count == sleeps
    asyncio.run(run())


@pytest.mark.parametrize('error,kind', [(Forbidden('blocked'), UserBlockedError),
    (BadRequest('chat not found'), ChatNotFoundError), (TimedOut(), TelegramMessageError)])
def test_send_exception_classification_without_retry(error, kind):
    async def run():
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=error))
        with pytest.raises(kind) as result:
            await safe_send_message(bot, 1, 'Hello')
        assert result.value.__cause__ is error
        bot.send_message.assert_awaited_once()
    asyncio.run(run())


def test_late_chunk_429_never_replays_successful_prefix(monkeypatch):
    monkeypatch.setattr('modules.telegram_transport.asyncio.sleep', AsyncMock())
    async def run():
        first, second = SimpleNamespace(message_id=1), SimpleNamespace(message_id=2)
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=[first, RetryAfter(1), second]))
        text = 'Я' * 4097
        assert await safe_send_message(bot, 1, text) is first
        assert [call.kwargs['text'] for call in bot.send_message.await_args_list] == [text[:4096], 'Я', 'Я']
    asyncio.run(run())


def test_late_chunk_timeout_reports_partial_delivery_without_replay():
    async def run():
        first = SimpleNamespace(message_id=1)
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=[first, TimedOut()]))
        with pytest.raises(PartialDeliveryError) as result:
            await safe_send_message(bot, 1, 'a' * 5000)
        assert result.value.messages == (first,)
        assert not is_formatting_error(result.value) and bot.send_message.await_count == 2
    asyncio.run(run())


def test_overlong_rich_text_rejected_before_any_send():
    async def run():
        bot = SimpleNamespace(send_message=AsyncMock())
        with pytest.raises(MessageTooLongError):
            await safe_send_message(bot, 1, '*' + 'я' * 5000 + '*', parse_mode='MarkdownV2')
        bot.send_message.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('edit_error,send_count,message_id', [
    (BadRequest('Message is not modified'), 0, 10),
    (BadRequest('Message to edit not found'), 1, 11),
    (BadRequest('not enough rights'), 0, None), (TimedOut(), 0, None),
])
def test_solution_fallback_is_limited_and_checkpointed(monkeypatch, edit_error, send_count, message_id):
    monkeypatch.setattr('modules.telegram_transport.asyncio.sleep', AsyncMock())
    async def run():
        poll = {'question_details': {'explanation': '2 + 2 = 4!'}, 'solution_placeholder_message_id': 10}
        engine = engine_for(poll)
        saved = []
        async def checkpoint():
            saved.append(deepcopy(poll))
        bot = SimpleNamespace(edit_message_text=AsyncMock(side_effect=edit_error),
                              send_message=AsyncMock(return_value=SimpleNamespace(message_id=11)))
        context = SimpleNamespace(bot=bot)
        assert await engine.send_solution_if_available(context, 1, 'solution-poll', persist_solution=checkpoint) == message_id
        assert saved[0]['solution_delivery'] == 'sending'
        assert bot.send_message.await_count == send_count
        assert await engine.send_solution_if_available(context, 1, 'solution-poll', persist_solution=checkpoint) == message_id
        assert bot.send_message.await_count == send_count
        if message_id:
            assert saved[-1]['solution_sent'] and saved[-1]['solution_message_id'] == message_id
    asyncio.run(run())


def test_solution_send_intent_blocks_replay_after_restart_or_concurrent_callback():
    async def run():
        poll = {'question_details': {'explanation': 'Answer'}}
        engine = engine_for(poll)
        async def checkpoint():
            # A second callback sees the in-flight intent before it can send.
            assert await engine.send_solution_if_available(context, 1, 'solution-poll') is None
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=TimedOut()))
        context = SimpleNamespace(bot=bot)
        assert await engine.send_solution_if_available(context, 1, 'solution-poll', persist_solution=checkpoint) is None
        restored = engine_for(deepcopy(poll))
        assert await restored.send_solution_if_available(context, 1, 'solution-poll') is None
        bot.send_message.assert_awaited_once()
    asyncio.run(run())


def test_failed_solution_intent_commit_prevents_telegram_send():
    async def run():
        engine = engine_for({'question_details': {'solution': 'Answer'}})
        bot = SimpleNamespace(send_message=AsyncMock())
        with pytest.raises(RuntimeError):
            await engine.send_solution_if_available(SimpleNamespace(bot=bot), 1, 'solution-poll',
                persist_solution=AsyncMock(side_effect=RuntimeError('DB down')))
        bot.send_message.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('user,indices,ids', [(None, [1], ['b']), (User(1, 'A', False), [], []),
    (User(1, 'A', False), [1], ['a']), (User(1, 'A', False), [0, 1], ['a', 'b'])])
def test_invalid_votes_do_not_score_or_poison_retry_cache(user, indices, ids):
    async def run():
        score = SimpleNamespace(update_score_and_get_motivation=AsyncMock())
        state = SimpleNamespace(get_current_poll_data=lambda _: {'chat_id': 1, 'correct_option_index': 1,
                                'option_count': 2, 'option_persistent_ids': ['a', 'b']})
        handler = CustomPollAnswerHandler(None, state, score, SimpleNamespace(postgres_storage=None), None)
        update = SimpleNamespace(poll_answer=SimpleNamespace(user=user, option_ids=indices,
                                 option_persistent_ids=ids, poll_id='p'))
        await handler.handle_poll_answer(update, SimpleNamespace())
        score.update_score_and_get_motivation.assert_not_awaited()
        assert not getattr(handler, '_processed_answers', set())
    asyncio.run(run())
