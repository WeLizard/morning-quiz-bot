"""Keeps `Chat.is_active` in sync with what Telegram tells the bot.

The Mini App reads the same flag, so a group the bot left or was kicked from (or that
became a supergroup with a new id) disappears from the player's chat list instead of
producing errors on the home screen.
"""
import logging

from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ChatMemberHandler, ContextTypes, MessageHandler, filters

from storage.chat_availability import migrate_chat, set_chat_active

logger = logging.getLogger(__name__)

_GROUPS = {ChatType.GROUP, ChatType.SUPERGROUP}
_GONE = {ChatMemberStatus.LEFT, ChatMemberStatus.BANNED}
_PRESENT = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}


class ChatAvailabilityHandlers:
    def __init__(self, database):
        self.database = database

    async def my_chat_member(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        change = update.my_chat_member
        if change is None or change.chat.type not in _GROUPS:
            return
        status = change.new_chat_member.status
        if status not in _GONE and status not in _PRESENT:
            return
        try:
            await set_chat_active(self.database, change.chat.id, status in _PRESENT)
        except Exception:
            logger.exception('Не удалось обновить доступность чата %s', change.chat.id)

    async def migrated(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.effective_message
        if message is None:
            return
        # Telegram sends the event twice: into the old chat (migrate_to) and the new one (migrate_from).
        old_id = message.chat.id if message.migrate_to_chat_id else message.migrate_from_chat_id
        new_id = message.migrate_to_chat_id or message.chat.id
        if not old_id or not new_id:
            return
        try:
            await migrate_chat(self.database, old_id, new_id)
        except Exception:
            logger.exception('Не удалось перенести чат %s -> %s', old_id, new_id)

    def get_handlers(self):
        return [
            ChatMemberHandler(self.my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER),
            MessageHandler(filters.StatusUpdate.MIGRATE, self.migrated),
        ]
