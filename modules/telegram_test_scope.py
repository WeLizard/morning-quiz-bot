"""Fail-closed transport for the explicitly authorized private Telegram dev chat."""
from collections import deque
from datetime import datetime, timezone
import json

from telegram import Update
from telegram.error import Forbidden
from telegram.request import BaseRequest


class PrivateTestScope:
    READ_METHODS = {'getMe', 'getWebhookInfo', 'getUpdates'}
    CHAT_METHODS = {
        'getChat', 'getChatMember', 'getChatAdministrators', 'getChatMemberCount', 'getChatMenuButton',
        'sendMessage', 'sendPhoto', 'sendPoll', 'sendChatAction', 'stopPoll',
        'editMessageText', 'editMessageCaption', 'editMessageReplyMarkup',
        'deleteMessage', 'deleteMessages',
    }

    def __init__(self, chat_id, bot_id):
        if type(chat_id) is not int or chat_id <= 0 or type(bot_id) is not int or bot_id <= 0:
            raise ValueError('A positive private chat ID and expected test bot ID are required')
        self.chat_id, self.bot_id = chat_id, bot_id
        self.poll_ids = set()
        self.callback_ids = deque(maxlen=1000)
        self.events = deque(maxlen=200)

    def event(self, name, **data):
        self.events.append({'at': datetime.now(timezone.utc).isoformat(), 'event': name, **data})

    def accepts(self, update):
        user = update.effective_user
        if not user or user.is_bot or user.id != self.chat_id:
            return False
        if update.poll_answer:
            return update.poll_answer.poll_id in self.poll_ids
        chat = update.effective_chat
        if not chat or chat.type != 'private' or chat.id != self.chat_id:
            return False
        if update.callback_query:
            query = update.callback_query
            if (not query.message or not query.message.from_user
                    or query.message.from_user.id != self.bot_id):
                return False
            self.callback_ids.append(query.id)
            return True
        return bool(update.message)

    def permits(self, method, params):
        if method in self.READ_METHODS:
            return True
        if method in self.CHAT_METHODS:
            return (str(params.get('chat_id')) == str(self.chat_id)
                    and not any(key in params for key in ('business_connection_id', 'inline_message_id', 'from_chat_id')))
        if method == 'answerCallbackQuery':
            return params.get('callback_query_id') in self.callback_ids
        if method == 'setChatMenuButton':
            return str(params.get('chat_id')) == str(self.chat_id)
        if method == 'setMyCommands':
            scope = params.get('scope')
            return isinstance(scope, dict) and scope.get('type') == 'chat' and str(scope.get('chat_id')) == str(self.chat_id)
        return False


class ScopedRequest(BaseRequest):
    def __init__(self, inner, scope, token):
        self.inner, self.scope = inner, scope
        self._base = 'https://api.telegram.org/bot' + token + '/'

    @property
    def read_timeout(self):
        return self.inner.read_timeout

    async def initialize(self):
        await self.inner.initialize()

    async def shutdown(self):
        await self.inner.shutdown()

    async def do_request(self, url, method, request_data=None, **kwargs):
        name = url[len(self._base):] if url.startswith(self._base) else ''
        params = request_data.parameters if request_data else {}
        if not self.scope.permits(name, params):
            self.scope.event('blocked_outbound')
            raise Forbidden('Test transport blocked a method or recipient outside the authorized private chat')
        status, raw = await self.inner.do_request(url, method, request_data=request_data, **kwargs)
        if name != 'getUpdates':
            self.scope.event('telegram_call', method=name, status=status)
        if status == 200 and name == 'sendPoll':
            result = json.loads(raw).get('result') or {}
            poll_id = (result.get('poll') or {}).get('id')
            if poll_id:
                self.scope.poll_ids.add(poll_id)
        return status, raw


def menu_command(update, commands, bot):
    """Dispatch start-menu buttons through real command/ConversationHandler entry points."""
    query = update.callback_query
    command = {
        'start_quiz': commands.quiz, 'start_mystats': commands.mystats,
        'start_global_top': commands.global_top, 'start_settings': commands.admin_settings,
        'start_help': commands.help, 'start_categories': commands.categories,
    }.get(query.data) if query else None
    if not command or not query.message:
        return update
    text = '/' + command
    return Update.de_json({'update_id': update.update_id, 'message': {
        'message_id': query.message.message_id, 'date': int(query.message.date.timestamp()),
        'chat': query.message.chat.to_dict(), 'from': query.from_user.to_dict(), 'text': text,
        'entities': [{'type': 'bot_command', 'offset': 0, 'length': len(text)}],
    }}, bot)
