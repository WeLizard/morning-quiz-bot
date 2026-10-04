#handlers/rating_handlers.py
import logging
from typing import List, Dict, Any, Optional

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from telegram.constants import ParseMode

from app_config import AppConfig
from modules.score_manager import ScoreManager
from utils import escape_markdown_v2

logger = logging.getLogger(__name__)

class RatingHandlers:
    def __init__(self, app_config: AppConfig, score_manager: ScoreManager):
        self.app_config = app_config
        self.score_manager = score_manager

    async def _rating_command_logic(self, update: Update, context: ContextTypes.DEFAULT_TYPE, global_rating: bool) -> None:
        if not update.message:
            logger.warning("_rating_command_logic вызван без update.message.")
            return

        chat_id_for_query: Optional[int] = None
        if not global_rating:
            if update.effective_chat:
                chat_id_for_query = update.effective_chat.id
            else:
                logger.error("Неглобальный рейтинг вызван без update.effective_chat.")
                await update.message.reply_text(escape_markdown_v2("Не удалось определить чат для рейтинга."), parse_mode=ParseMode.MARKDOWN_V2)
                return

        try:
            if global_rating:
                top_users = await self.score_manager.get_global_rating(top_n=self.app_config.rating_display_limit)
                title_unescaped = "🌍 Глобальный топ игроков"
            else:
                top_users = await self.score_manager.get_chat_rating(
                    chat_id=chat_id_for_query, top_n=self.app_config.rating_display_limit,
                )
                title_unescaped = "🏆 Топ игроков в этом чате"
        except Exception:
            logger.exception("Не удалось прочитать рейтинг")
            await update.message.reply_text("Статистика временно недоступна. Попробуйте позже.")
            return

        if not top_users:
            if global_rating:
                reply_text_unescaped = "Пока нет данных для глобального рейтинга."
            else:
                reply_text_unescaped = "Пока нет данных для рейтинга в этом чате."
            await update.message.reply_text(escape_markdown_v2(reply_text_unescaped), parse_mode=ParseMode.MARKDOWN_V2)
            return

        formatted_rating_text = self.score_manager.format_scores(
            scores_list=top_users,
            title=title_unescaped,
            is_session_score=False
        )

        try:
            sent_msg = await update.message.reply_text(formatted_rating_text, parse_mode=ParseMode.MARKDOWN_V2)
            # Добавляем сообщение рейтинга в список для удаления
            bot_state = context.bot_data.get('bot_state')
            if bot_state:
                if update.effective_chat:
                    bot_state.add_message_for_deletion(update.effective_chat.id, sent_msg.message_id)
        except Exception as e:
            logger.error(f"Ошибка при отправке рейтинга (global={global_rating}): {e}\nТекст: {formatted_rating_text[:500]}")
            await update.message.reply_text(escape_markdown_v2("Не удалось отобразить рейтинг."), parse_mode=ParseMode.MARKDOWN_V2)

    async def top_chat_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._rating_command_logic(update, context, global_rating=False)

    async def top_global_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._rating_command_logic(update, context, global_rating=True)

    async def my_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_user or not update.effective_chat:
            return

        user = update.effective_user
        chat_id = update.effective_chat.id
        user_id_str = str(user.id)
        user_first_name_escaped = escape_markdown_v2(user.first_name)

        try:
            profile = (await self.score_manager.get_session_profiles(chat_id, [user_id_str])).get(user_id_str, {})
            user_chat_stats = profile.get("chat")
            user_global_stats = profile.get("global")
        except Exception:
            logger.exception("Не удалось прочитать профиль")
            await update.message.reply_text("Статистика временно недоступна. Попробуйте позже.")
            return

        reply_parts = [escape_markdown_v2(f"📊 Ваша статистика, {user.first_name}")]

        if user_chat_stats:
            score_chat = user_chat_stats.get('score', 0)
            answered_chat = user_chat_stats.get('answered_polls_count', 0)
            avg_score_chat = (score_chat / answered_chat) if answered_chat > 0 else 0.0
            chat_title_val = update.effective_chat.title if update.effective_chat.title else "этот чат"
            chat_title_escaped = escape_markdown_v2(chat_title_val)

            reply_parts.append(escape_markdown_v2(f"\n🏆 В чате ({chat_title_val}):"))
            # ИСПРАВЛЕНО: Округляем score_chat до 1 знака для устранения проблемы с плавающей точкой
            reply_parts.append(escape_markdown_v2(f"⭐ Рейтинг: {round(score_chat, 1)}"))
            reply_parts.append(escape_markdown_v2(f"🙋 Отвечено на опросы: {answered_chat}"))
            reply_parts.append(escape_markdown_v2(f"🎯 Средний балл за опрос: {avg_score_chat:.2f}"))
        else:
            reply_parts.append(escape_markdown_v2(f"\n{user.first_name}, у вас пока нет статистики в этом чате."))

        if user_global_stats:
            global_total_score = user_global_stats.get('total_score', 0)
            global_answered_polls = user_global_stats.get('answered_polls', 0)
            global_avg_score = user_global_stats.get('average_score_per_poll', 0.0)

            reply_parts.append(escape_markdown_v2(f"\n🌍 Глобально:"))
            # ИСПРАВЛЕНО: Округляем глобальный рейтинг до 1 знака после запятой
            reply_parts.append(escape_markdown_v2(f"⭐ Общий рейтинг: {round(global_total_score, 1)}"))
            reply_parts.append(escape_markdown_v2(f"🙋 Всего отвечено на опросы: {global_answered_polls}"))
            reply_parts.append(escape_markdown_v2(f"🎯 Средний балл за опрос: {global_avg_score:.1f}"))
        else:
             reply_parts.append(f"\n{escape_markdown_v2(f'{user.first_name}, у вас пока нет глобальной статистики.')}")

        final_reply_text: str
        if len(reply_parts) == 1:
            final_reply_text = escape_markdown_v2(f"{user.first_name}, данных для статистики пока нет.")
        else:
            final_reply_text = "\n".join(reply_parts)

        try:
            sent_msg = await update.message.reply_text(final_reply_text, parse_mode=ParseMode.MARKDOWN_V2)
            # Добавляем сообщение статистики в список для удаления
            bot_state = context.bot_data.get('bot_state')
            if bot_state:
                bot_state.add_message_for_deletion(chat_id, sent_msg.message_id)
        except Exception as e:
            logger.error(f"Ошибка при отправке my_stats: {e}. Текст (начало):\n{final_reply_text[:500]}")
            await update.message.reply_text(escape_markdown_v2("Не удалось отобразить вашу статистику."), parse_mode=ParseMode.MARKDOWN_V2)

    def get_handlers(self) -> List[CommandHandler]:
        return [
            CommandHandler(self.app_config.commands.top, self.top_chat_command),
            CommandHandler(self.app_config.commands.global_top, self.top_global_command),
            CommandHandler(self.app_config.commands.mystats, self.my_stats_command),
        ]
