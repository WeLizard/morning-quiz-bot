#poll_answer_handler.py
import logging
from hashlib import sha256
from typing import Optional, TYPE_CHECKING

from telegram import Update, PollAnswer, User as TelegramUser
from telegram.ext import ContextTypes, PollAnswerHandler as PTBPollAnswerHandler
from telegram.constants import ParseMode

from utils import escape_markdown_v2
from modules.telegram_utils import safe_send_message, format_error_message
from modules.quiz_payload import selected_option_index

if TYPE_CHECKING:
    from app_config import AppConfig
    from state import BotState
    from modules.score_manager import ScoreManager
    from handlers.quiz_manager import QuizManager
    from data_manager import DataManager

logger = logging.getLogger(__name__)

class CustomPollAnswerHandler:
    def __init__(
        self,
        app_config: 'AppConfig',
        state: 'BotState',
        score_manager: 'ScoreManager',
        data_manager: 'DataManager',
        quiz_manager: 'QuizManager'
    ):
        self.app_config = app_config
        self.state = state
        self.score_manager = score_manager
        self.data_manager = data_manager
        self.quiz_manager = quiz_manager

    async def _handle_platform_answer(self, poll_answer, user) -> bool:
        """Resolve a v2 delivery and submit the same command used by Mini App."""
        storage = self.data_manager.postgres_storage
        if storage is None or getattr(storage, 'database', None) is None:
            return False
        from application.classic import ClassicApplicationService
        from storage.game_deliveries import GameDeliveries
        async with storage.database.transaction() as session:
            delivery = await GameDeliveries(session).resolve(
                channel='telegram', external_id=poll_answer.poll_id
            )
            if delivery is None:
                return False
            poll = {
                'option_count': len(delivery.metadata_json.get('option_persistent_ids') or []),
                'option_persistent_ids': delivery.metadata_json.get('option_persistent_ids') or [],
            }
            selected = selected_option_index(poll_answer, poll)
            if selected is None:
                logger.warning('Ignoring malformed platform vote for %s', poll_answer.poll_id)
                return True
            raw_id = f'{poll_answer.poll_id}:{user.id}'
            command = 'tg-answer:' + sha256(raw_id.encode()).hexdigest()[:48]
            try:
                await ClassicApplicationService(
                    storage.database, session,
                    rules=self.score_manager._classic_scoring_rules(),
                ).answer(
                    chat_id=delivery.chat_id,
                    user_id=user.id,
                    display_name=user.full_name,
                    round_id=delivery.round_id,
                    selected_option=selected,
                    command_id=command,
                )
            except (LookupError, PermissionError, RuntimeError, ValueError) as error:
                logger.info('Classic platform answer rejected: %s', type(error).__name__)
            return True

    async def handle_poll_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.poll_answer:
            logger.debug("handle_poll_answer: update.poll_answer is None, игнорируется.")
            return

        poll_answer: PollAnswer = update.poll_answer
        user: TelegramUser = poll_answer.user
        answered_poll_id: str = poll_answer.poll_id
        if user is None or not poll_answer.option_ids:
            return  # Chat votes and withdrawn votes are not scorable quiz answers.

        if await self._handle_platform_answer(poll_answer, user):
            return

        # ИСПРАВЛЕНО: Проверяем, не обрабатывали ли мы уже этот ответ
        # Создаем уникальный ключ для ответа
        answer_key = f"{answered_poll_id}_{user.id}"
        
        # Проверяем, не был ли этот ответ уже обработан
        if hasattr(self, '_processed_answers') and answer_key in self._processed_answers:
            logger.debug(f"Ответ {answer_key} уже был обработан, игнорируем дублирование")
            return
        
        # Инициализируем множество обработанных ответов, если его нет
        if not hasattr(self, '_processed_answers'):
            self._processed_answers = set()
        
        # Ограничиваем размер множества (очищаем старые записи)
        if len(self._processed_answers) > 1000:
            # Оставляем только последние 500 ответов
            self._processed_answers = set(list(self._processed_answers)[-500:])

        poll_info_from_state = self.state.get_current_poll_data(answered_poll_id)

        if not poll_info_from_state:
            logger.debug(
                f"Информация для poll_id {answered_poll_id} не найдена в state.current_polls. "
                f"Ответ от {user.full_name} (ID: {user.id}) проигнорирован."
            )
            return

        chat_id_int: int = poll_info_from_state["chat_id"]
        quiz_type_of_poll: str = poll_info_from_state.get("quiz_type", "unknown_type")
        correct_option_index_for_this_poll: int = poll_info_from_state["correct_option_index"]
        if self.data_manager.postgres_storage:
            quiz = self.state.get_active_quiz(chat_id_int)
            if not quiz or quiz.is_stopping:
                return

        chosen_index = selected_option_index(poll_answer, poll_info_from_state)
        if chosen_index is None:
            logger.warning('Ignoring malformed/mismatched quiz vote for %s', answered_poll_id)
            return
        is_answer_correct = chosen_index == correct_option_index_for_this_poll

        try:
            score_was_updated, motivational_msg_text_chat, motivational_msg_text_ls, streak_msg_text = await self.score_manager.update_score_and_get_motivation(
                chat_id=chat_id_int, user=user, poll_id=answered_poll_id,
                is_correct=is_answer_correct, quiz_type_of_poll=quiz_type_of_poll,
            )
        except Exception as exc:
            from storage.classic_sessions import ClassicSessionConflict
            from storage.admin_actions import BotAccessBlocked
            if isinstance(exc, (ClassicSessionConflict, BotAccessBlocked)):
                return
            raise  # Do not poison the retry cache when persistence fails.
        self._processed_answers.add(answer_key)
        if self.data_manager.postgres_storage:
            from storage.admin_actions import AdminActions
            if not await AdminActions(self.data_manager.postgres_storage.database).allowed(chat_id_int, user.id):
                return
        
        # ДЕБАГ: Логируем результат обработки
        logger.info(f"🔍 ДЕБАГ: Результат update_score_and_get_motivation:")
        logger.info(f"🔍 ДЕБАГ: score_was_updated: {score_was_updated}")
        logger.info(f"🔍 ДЕБАГ: motivational_msg_text_chat: {motivational_msg_text_chat}")
        logger.info(f"🔍 ДЕБАГ: motivational_msg_text_ls: {motivational_msg_text_ls}")
        logger.info(f"🔍 ДЕБАГ: streak_msg_text: {streak_msg_text}")

        # Отправляем сообщения если есть что отправлять
        has_chat_message = motivational_msg_text_chat or streak_msg_text
        if has_chat_message:
            logger.info(f"🔍 ДЕБАГ: Отправляем мотивационное сообщение...")
            
            # Отправляем чатовые ачивки в групповой чат (остаются навсегда)
            if motivational_msg_text_chat:
                try:
                    logger.info(f"🔍 ДЕБАГ: Отправляем чатовую ачивку в групповой чат {chat_id_int}")
                    motivational_msg = await safe_send_message(
                        bot=context.bot,
                        chat_id=chat_id_int,
                        text=motivational_msg_text_chat,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    logger.info(f"✅ Сообщение о чатовой ачивке отправлено в чат {chat_id_int}")
                    # Чатовые ачивки НЕ добавляются в список для удаления (остаются навсегда)
                    
                except Exception as e:
                    error_msg = format_error_message(e, "отправка чатовой ачивки")
                    logger.error(f"❌ Не удалось отправить сообщение о чатовой ачивке в чат {chat_id_int}: {error_msg}")
            
            # Отправляем streak ачивки в групповой чат (будут удалены)
            if streak_msg_text:
                try:
                    logger.info(f"🔍 ДЕБАГ: Отправляем streak ачивку в групповой чат {chat_id_int}")
                    streak_msg = await safe_send_message(
                        bot=context.bot,
                        chat_id=chat_id_int,
                        text=streak_msg_text,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    logger.info(f"✅ Сообщение о streak ачивке отправлено в чат {chat_id_int}")
                    
                    # Streak ачивки добавляются в список для удаления
                    active_quiz = self.state.get_active_quiz(chat_id_int)
                    if active_quiz:
                        active_quiz.message_ids_to_delete.add(streak_msg.message_id)
                        logger.info(f"📝 ID сообщения о streak ачивке {streak_msg.message_id} добавлен в список для удаления")
                    
                except Exception as e:
                    error_msg = format_error_message(e, "отправка streak ачивки")
                    logger.error(f"❌ Не удалось отправить сообщение о streak ачивке в чат {chat_id_int}: {error_msg}")
            
            # Отправляем в личные сообщения пользователю (только чатовые ачивки, без streak)
            if chat_id_int != user.id and motivational_msg_text_ls:  # ИСПРАВЛЕНО: Не отправляем в ЛС если пользователь уже в личном чате И если есть что отправлять
                try:
                    logger.info(f"🔍 ДЕБАГ: Отправляем в ЛС пользователю {user.id}")
                    
                    # Пытаемся отправить сообщение (только чатовые ачивки, без streak)
                    await safe_send_message(
                        bot=context.bot,
                        chat_id=user.id,
                        text=motivational_msg_text_ls,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    logger.info(f"✅ Сообщение о чатовой ачивке отправлено пользователю {user.id} в ЛС")
                    
                except Exception as e:
                    # Если не удалось отправить в ЛС, логируем это (это нормально)
                    if "bot was blocked by the user" in str(e).lower() or "user not found" in str(e).lower():
                        logger.info(f"ℹ️ Пользователь {user.id} заблокировал бота или не начинал с ним диалог - ЛС недоступны")
                    else:
                        logger.warning(f"⚠️ Не удалось отправить сообщение о чатовой ачивке пользователю {user.id} в ЛС: {e}")
            elif chat_id_int == user.id:
                logger.info(f"ℹ️ Пользователь {user.id} уже в личном чате - пропускаем отправку в ЛС для предотвращения дублирования")
            elif not motivational_msg_text_ls:
                logger.info(f"ℹ️ Нет сообщений для отправки в ЛС (только streak ачивки)")
        else:
            logger.info(f"🔍 ДЕБАГ: Нет сообщений для отправки в чат")

        # СТАТИСТИКА КАТЕГОРИЙ БОЛЬШЕ НЕ ОБНОВЛЯЕТСЯ ПРИ КАЖДОМ ОТВЕТЕ
        # Теперь она обновляется только при старте квиза (один раз за квиз)
        # Это исправляет проблему с неправильным подсчётом использования категорий

        active_quiz_session = self.state.get_active_quiz(chat_id_int)
        if active_quiz_session and answered_poll_id in active_quiz_session.active_poll_ids_in_session: # ИСПРАВЛЕНО ИМЯ
             if self.quiz_manager:
                 await self.quiz_manager._handle_early_answer_for_session(context, chat_id_int, answered_poll_id)

    def get_handler(self) -> PTBPollAnswerHandler:
        return PTBPollAnswerHandler(self.handle_poll_answer)
