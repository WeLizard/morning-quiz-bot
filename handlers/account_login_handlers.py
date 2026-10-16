"""Bot side of the browser Telegram login: show the request, approve or cancel it."""
import logging
import re
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, filters

from storage.telegram_login import TelegramLogins

logger = logging.getLogger(__name__)

MOSCOW = ZoneInfo('Europe/Moscow')
START_PATTERN = r'^/start(?:@\w+)? login_[A-Za-z0-9_-]{20,64}$'
CALLBACK_PATTERN = r'^qwlogin:[0-9a-f]{32}:(ok|no)$'
STALE = 'Ссылка для входа устарела. Начни вход заново на сайте.'
FAILED = 'Не удалось подтвердить вход. Начни вход заново на сайте.'
# The bot runs with Defaults(parse_mode=MarkdownV2); these messages are plain text and the
# device label comes from the browser's User-Agent, so markup must never be applied to them.
PLAIN = {'parse_mode': None}


class AccountLoginHandlers:
    def __init__(self, database, *, logins=None):
        self.logins = logins or TelegramLogins(database)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message, user = update.effective_message, update.effective_user
        if message is None or user is None or user.is_bot:
            return
        token = (message.text or '').split(' ', 1)[1][len('login_'):]
        info = await self.logins.describe(token, user.id)
        if info is None or info['state'] in {'expired', 'closed'}:
            await message.reply_text(STALE, **PLAIN)
            return
        if info['state'] == 'approved':
            await message.reply_text('Вход уже подтверждён. Вернись в браузер.', **PLAIN)
            return
        created = info['created_at'].astimezone(MOSCOW).strftime('%H:%M')
        text = (f'Вход в QuizzyWizzy в браузере\nУстройство: {info["client_hint"] or "неизвестно"}\n'
                f'Запрос создан в {created} (МСК).\n'
                'Если ссылку тебе прислал кто-то другой — нажми «Отмена»: '
                'кнопка «Войти» откроет ему твой профиль.')
        await message.reply_text(text, **PLAIN, reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton('Войти', callback_data=f'qwlogin:{info["id"]}:ok'),
            InlineKeyboardButton('Отмена', callback_data=f'qwlogin:{info["id"]}:no')]]))

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query, user = update.callback_query, update.effective_user
        if query is None or user is None:
            return
        _, request_id, action = query.data.split(':')
        chat = query.message.chat if query.message else None
        # The buttons only ever exist in the player's own private chat with the bot.
        if user.is_bot or chat is None or chat.type != 'private' or chat.id != user.id:
            await query.answer('Подтвердить вход можно только в личном чате с ботом.', show_alert=True)
            return
        if action == 'ok':
            status = await self.logins.approve_by_id(
                request_id, user.id, user.full_name, is_bot=user.is_bot)
            text = {'approved': 'Вход подтверждён. Вернись в браузер.',
                    'already': 'Вход уже подтверждён. Вернись в браузер.',
                    'cancelled': 'Вход был отменён. Начни вход заново на сайте.',
                    'expired': STALE}.get(status, FAILED)
        else:
            status = await self.logins.cancel_by_id(request_id, user.id, is_bot=user.is_bot)
            text = {'cancelled': 'Вход отменён.',
                    'already': 'Вход уже был подтверждён, отменить его нельзя.',
                    'expired': STALE}.get(status, FAILED)
        await query.answer()
        try:
            await query.edit_message_text(text, **PLAIN)
        except Exception:  # The decision is stored; a stale message edit must not look like a failure.
            logger.debug('Could not edit login message', exc_info=True)

    def get_handlers(self):
        return [
            CommandHandler('start', self.start,
                           filters=filters.ChatType.PRIVATE & filters.Regex(START_PATTERN)),
            CallbackQueryHandler(self.callback, pattern=CALLBACK_PATTERN),
        ]
