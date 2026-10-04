"""Early update gate; no Telegram membership bans and no JSON fallback."""
import logging

from telegram import Update
from telegram.ext import ApplicationHandlerStop, TypeHandler

from storage.admin_actions import AdminActions

logger = logging.getLogger(__name__)


def moderation_handler(database):
    async def gate(update, context):
        user = update.effective_user
        chat = update.effective_chat
        try:
            command = (update.effective_message.text or '').split()[0].split('@')[0] if update.effective_message and update.effective_message.text else ''
            # The maintenance command still checks superadmin privileges itself.
            allowed = await AdminActions(database).allowed(chat.id if chat else None, user.id if user else None,
                                                           ignore_maintenance=command == '/maintenance')
        except Exception:
            # A failed read must never turn into permission; no reply to a potentially banned chat.
            logger.exception('Moderation lookup failed; update suppressed')
            raise ApplicationHandlerStop
        if not allowed:
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
