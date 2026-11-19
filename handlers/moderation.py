"""Early update gate; no Telegram membership bans and no JSON fallback."""
import logging

from telegram import Update
from telegram.ext import ApplicationHandlerStop, TypeHandler

from modules.telegram_api_ext import update_identity
from modules.telegram_widgets import answer_widget_query, widget_query_of
from storage.admin_actions import AdminActions

logger = logging.getLogger(__name__)


def moderation_handler(database):
    async def gate(update, context):
        user = update.effective_user
        chat = update.effective_chat
        # Widget queries (Bot API 10.4) carry no effective_user/chat in PTB 22.8: read them from the query.
        chat_id, user_id = update_identity(update)
        try:
            command = (update.effective_message.text or '').split()[0].split('@')[0] if update.effective_message and update.effective_message.text else ''
            # The maintenance command still checks superadmin privileges itself.
            allowed = await AdminActions(database).allowed(chat_id, user_id,
                                                           ignore_maintenance=command == '/maintenance')
        except Exception:
            # A failed read must never turn into permission; no reply to a potentially banned chat.
            logger.exception('Moderation lookup failed; update suppressed')
            raise ApplicationHandlerStop
        if not allowed:
            query = widget_query_of(update)
            if query is not None:
                try:  # An unanswered widget waits 15 s and shows TIMEOUT; say "unavailable" at once.
                    await answer_widget_query(update.get_bot(), query.id, {'error': 'unavailable'})
                except Exception:
                    logger.warning('Widget query %s not answered by the moderation gate', query.id, exc_info=True)
            if chat and update.effective_message:
                try:
                    from storage.system_control import SystemControl
                    control = SystemControl(database)
                    notice = await control.claim_notification(chat.id, user.id if user else None)
                    if notice:
                        text = '🔧 Бот на обслуживании. ' + notice['reason']
                        if update.callback_query:
                            await update.callback_query.answer(text[:180], show_alert=True)
                        else:
                            message = await update.effective_message.reply_text(text, parse_mode=None)
                            await control.notification_sent(chat.id, message.message_id, notice['revision'])
                except Exception:
                    logger.exception('Maintenance notice failed; update remains suppressed')
            raise ApplicationHandlerStop
    return TypeHandler(Update, gate)
