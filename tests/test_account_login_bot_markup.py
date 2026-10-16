"""Browser-login bot messages under the real PTB Defaults(parse_mode=MarkdownV2).

Regression (sandbox, 2026-10-15): '/start login_…' answered «Произошла внутренняя ошибка»
because the plain text «(МСК)» and the User-Agent device label were sent as MarkdownV2.
The recording request below rejects unescaped MarkdownV2 like Telegram does.
"""
import asyncio
from datetime import datetime, timezone
import json
import re

from telegram import Update
from telegram.ext import Defaults, ExtBot
from telegram.request import BaseRequest

from handlers.account_login_handlers import AccountLoginHandlers

BOT_ID, UID = 123456, 981033000001
REQUEST_ID = 'a' * 32
HINT = 'Chrome_120.0 (Windows 10; x64) [beta] v1.2-rc*'
RESERVED = re.compile(r'(?<!\\)[_*\[\]()~`>#+\-=|{}.!]')


class TelegramLikeRequest(BaseRequest):
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
        for key, value in (request_data.json_parameters if request_data else {}).items():
            try:
                fields[key] = json.loads(value)
            except json.JSONDecodeError:
                fields[key] = value
        self.calls.append((endpoint, fields))
        if fields.get('parse_mode') == 'MarkdownV2' and RESERVED.search(fields.get('text', '')):
            return 400, json.dumps({'ok': False, 'error_code': 400, 'description':
                "Bad Request: can't parse entities: character '(' is reserved and must be "
                "escaped with the preceding '\\'"}).encode()
        if endpoint == 'getMe':
            result = {'id': BOT_ID, 'is_bot': True, 'first_name': 'Local', 'username': 'local_test_bot'}
        elif endpoint in {'sendMessage', 'editMessageText'}:
            result = {'message_id': 7, 'date': 1700000000, 'chat': {'id': UID, 'type': 'private'},
                      'text': fields.get('text', '')}
        elif endpoint == 'answerCallbackQuery':
            result = True
        else:
            raise AssertionError(f'Unexpected API method: {endpoint}')
        return 200, json.dumps({'ok': True, 'result': result}).encode()


class FakeLogins:
    def __init__(self):
        self.approved, self.cancelled = [], []

    async def describe(self, token, viewer=None):
        return {'id': REQUEST_ID, 'client_hint': HINT, 'state': 'pending',
                'created_at': datetime(2026, 10, 15, 14, 50, tzinfo=timezone.utc)}

    async def approve_by_id(self, request_id, uid, name, *, is_bot=False):
        self.approved.append((request_id, uid))
        return 'approved'

    async def cancel_by_id(self, request_id, uid, *, is_bot=False):
        self.cancelled.append((request_id, uid))
        return 'cancelled'


USER = {'id': UID, 'is_bot': False, 'first_name': 'Тест_Игрок (1).'}
CHAT = {'id': UID, 'type': 'private'}


def message_update(bot, text):
    return Update.de_json({'update_id': 1, 'message': {
        'message_id': 5, 'date': 1700000000, 'chat': CHAT, 'from': USER, 'text': text}}, bot)


def callback_update(bot, action):
    return Update.de_json({'update_id': 2, 'callback_query': {
        'id': 'cb-1', 'chat_instance': 'ci', 'from': USER, 'data': f'qwlogin:{REQUEST_ID}:{action}',
        'message': {'message_id': 7, 'date': 1700000000, 'chat': CHAT, 'text': 'Вход в QuizzyWizzy'}}}, bot)


def test_login_messages_are_plain_text_under_markdown_v2_defaults():
    async def run():
        request = TelegramLikeRequest()
        logins = FakeLogins()
        handlers = AccountLoginHandlers(None, logins=logins)
        async with ExtBot(f'{BOT_ID}:LOCAL_TEST_ONLY', request=request, get_updates_request=TelegramLikeRequest(),
                          defaults=Defaults(parse_mode='MarkdownV2')) as bot:
            # Control: the default really applies MarkdownV2 and the Telegram-like stub rejects the text.
            control = await bot.send_message(UID, 'Запрос создан в 17:50 (МСК).', parse_mode=None)
            assert control.text
            assert 'parse_mode' not in request.calls[-1][1]
            try:
                await bot.send_message(UID, 'Запрос создан в 17:50 (МСК).')
            except Exception as error:  # telegram.error.BadRequest
                assert "parse entities" in str(error)
            else:
                raise AssertionError('the stub must reject unescaped MarkdownV2 like Telegram')

            await handlers.start(message_update(bot, '/start login_' + 'T' * 32), None)
            endpoint, fields = request.calls[-1]
            assert endpoint == 'sendMessage' and 'parse_mode' not in fields
            assert HINT in fields['text'] and '(МСК)' in fields['text'] and '\\' not in fields['text']
            assert [b['callback_data'] for b in fields['reply_markup']['inline_keyboard'][0]] == [
                f'qwlogin:{REQUEST_ID}:ok', f'qwlogin:{REQUEST_ID}:no']

            for action, expected in (('ok', 'Вход подтверждён. Вернись в браузер.'), ('no', 'Вход отменён.')):
                await handlers.callback(callback_update(bot, action), None)
                edits = [f for e, f in request.calls if e == 'editMessageText']
                assert edits and edits[-1]['text'] == expected and 'parse_mode' not in edits[-1]
            assert logins.approved == [(REQUEST_ID, UID)] and logins.cancelled == [(REQUEST_ID, UID)]

        # Stale link: the plain reply goes out without markup as well.
        stale_logins = FakeLogins()
        async def missing(token, viewer=None):
            return None
        stale_logins.describe = missing
        stale_request = TelegramLikeRequest()
        async with ExtBot(f'{BOT_ID}:LOCAL_TEST_ONLY', request=stale_request, get_updates_request=TelegramLikeRequest(),
                          defaults=Defaults(parse_mode='MarkdownV2')) as bot:
            await AccountLoginHandlers(None, logins=stale_logins).start(
                message_update(bot, '/start login_' + 'S' * 32), None)
        endpoint, fields = stale_request.calls[-1]
        assert endpoint == 'sendMessage' and 'устарела' in fields['text'] and 'parse_mode' not in fields
    asyncio.run(run())
