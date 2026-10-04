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
        self.local_message_ids = deque(maxlen=1000)
        self.events = deque(maxlen=200)
        self.local_delivery = False
        self.local_runtime = None

    def enable_local_delivery(self):
        """Use a local Telegram-shaped result only for the opted-in private Mini App game.

        The production bot and every group keep the normal Telegram transport.
        """
        if self.local_runtime is None:
            from modules.dev_runtime import DevRuntime
            self.local_runtime = DevRuntime(None)
            self.local_runtime.chat_id = self.chat_id
            self.local_runtime.room = {'id': self.chat_id, 'type': 'private', 'first_name': 'Игрок'}
            self.local_runtime.player = {'id': self.chat_id, 'is_bot': False, 'first_name': 'Игрок'}
        self.local_delivery = True

    def disable_local_delivery(self):
        self.local_delivery = False

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
        from modules.mini_bridge_worker import active_mini_action
        intent = active_mini_action.get()
        if intent and name == 'answerCallbackQuery' and params.get('callback_query_id') == 'mini-' + intent['id']:
            self.scope.event('mini_app_callback_ack')
            if params.get('text'):
                intent['error' if params.get('show_alert') else 'notice'] = str(params['text'])[:200]
            return 200, b'{"ok":true,"result":true}'
        if name == 'deleteMessage' and params.get('message_id') in self.scope.local_message_ids:
            return 200, b'{"ok":true,"result":true}'
        reply_id = (params.get('reply_parameters') or {}).get('message_id', params.get('reply_to_message_id'))
        if reply_id in self.scope.local_message_ids:
            # An app input has no native Telegram message to quote. Preserve the
            # response and uploads, but do not send a made-up reply target to Telegram.
            from telegram.request import RequestData
            request_data = RequestData([p for p in request_data._parameters
                                        if p.name not in {'reply_parameters', 'reply_to_message_id'}])
            params = request_data.parameters
        local_methods = {'getChat', 'getChatMember', 'getChatAdministrators', 'getChatMemberCount',
                         'sendMessage', 'sendPhoto', 'sendPoll', 'editMessageText',
                         'editMessageCaption', 'editMessageReplyMarkup', 'stopPoll',
                         'deleteMessage', 'deleteMessages'}
        if self.scope.local_delivery and name in local_methods:
            # The same bot handlers still form the game. For a one-player Mini App,
            # however, their output is an app event, not an outbound Telegram call.
            from modules.dev_runtime import OfflineRequest
            status, raw = await OfflineRequest(self.scope.local_runtime).do_request(
                'http://mini.local/' + name, method, request_data=request_data, **kwargs)
            self.scope.event('mini_local_delivery', method=name)
        else:
            status, raw = await self.inner.do_request(url, method, request_data=request_data, **kwargs)
        if name != 'getUpdates' and not (self.scope.local_delivery and name in local_methods):
            self.scope.event('telegram_call', method=name, status=status)
        if status == 200 and name == 'sendPoll':
            result = json.loads(raw).get('result') or {}
            poll_id = (result.get('poll') or {}).get('id')
            if poll_id:
                self.scope.poll_ids.add(poll_id)
        bridge = getattr(self.scope, 'mini_bridge', None)
        if bridge and status == 200 and name != 'getUpdates':
            from pathlib import Path
            media = None
            if name == 'sendPhoto':
                for upload in (request_data.multipart_data or {}).values():
                    candidate = Path(str(upload[0])).name
                    if Path(candidate).suffix.lower() in {'.webp', '.jpg', '.jpeg', '.png'}:
                        media = candidate
                        break
            await bridge.publish(name, params, json.loads(raw).get('result'), media)
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
