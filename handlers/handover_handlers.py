"""Groups that the old bot still serves: this bot stays quiet there until the chat is released.

See ``storage/bot_handover.py``. In such a group the bot greets once when it is added and then
leaves every message and command to the old bot; chat-membership and migration events still pass,
so the chat's availability and id stay correct for the switch day. Private chats are not gated.
"""
import logging
import time

from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ApplicationHandlerStop, TypeHandler

from storage import bot_handover

logger = logging.getLogger(__name__)

GROUPS = {ChatType.GROUP, ChatType.SUPERGROUP}
PRESENT = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}


def greeting(old_bot):
    lead = f'Пока квизы здесь ведёт @{old_bot}, а я жду' if old_bot else 'Пока я жду'
    return ('Привет! Я QuizzyWizzy — новый бот для квизов в этом чате. '
            f'{lead} дня переезда, чтобы не было двойных вопросов. '
            'В этот день настройки, расписание и очки чата перейдут ко мне, и я начну работать сам.')


class HandoverHandlers:
    def __init__(self, database, *, cache_seconds=15.0, clock=time.monotonic):
        self.database = database
        self.cache_seconds = cache_seconds
        self.clock = clock
        self._cached = None
        self._cached_at = 0.0

    async def _state(self, fresh=False):
        now = self.clock()
        if fresh or self._cached is None or now - self._cached_at >= self.cache_seconds:
            self._cached = await bot_handover.read(self.database)
            self._cached_at = now
        return self._cached

    async def gate(self, update: Update, context):
        chat = update.effective_chat
        if chat is None or chat.type not in GROUPS:
            return
        if update.my_chat_member is not None:
            await self._added(update.my_chat_member, context)
            return
        if update.chat_member is not None:
            return
        message = update.effective_message
        if message is not None and (message.migrate_to_chat_id or message.migrate_from_chat_id):
            old_id = message.chat.id if message.migrate_to_chat_id else message.migrate_from_chat_id
            new_id = message.migrate_to_chat_id or message.chat.id
            try:
                await bot_handover.follow_migration(self.database, old_id, new_id)
                self._cached = None
            except Exception:
                logger.exception('Handover list not moved from %s to %s', old_id, new_id)
            return
        try:
            state = await self._state()
        except Exception:
            # Without the list we cannot tell; answering would risk double quizzes in the old bot's chats.
            logger.exception('Handover list unreadable; group update %s suppressed', update.update_id)
            raise ApplicationHandlerStop
        if chat.id in state['chats']:
            raise ApplicationHandlerStop

    async def _added(self, change, context):
        if change.new_chat_member.status not in PRESENT or change.old_chat_member.status in PRESENT:
            return
        try:
            state = await self._state(fresh=True)
        except Exception:
            logger.exception('Handover list unreadable; no greeting for chat %s', change.chat.id)
            return
        if change.chat.id not in state['chats']:
            return
        try:
            await context.bot.send_message(change.chat.id, greeting(state['old_bot']), parse_mode=None)
        except Exception:
            logger.warning('Handover greeting not sent to chat %s', change.chat.id, exc_info=True)

    def get_handler(self):
        return TypeHandler(Update, self.gate)
