#handlers/quiz_manager.py
from __future__ import annotations
import asyncio
import logging
import time
from typing import List, Optional, Union, Dict, Any
from datetime import timedelta
import datetime as dt 
import pytz 
import re
import json

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, User as TelegramUser, Message, CallbackQuery
)
from telegram.ext import Application, ContextTypes, CommandHandler, ConversationHandler, CallbackQueryHandler, MessageHandler, filters
from concurrent.futures import ThreadPoolExecutor
import asyncio
import functools

# Lightweight offload executor to avoid blocking event loop in sync DB/IO calls
# Increased max_workers to handle more concurrent I/O operations
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="quiz-io")

async def run_sync(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_EXECUTOR, functools.partial(func, *args, **kwargs))
from telegram.constants import ParseMode
from telegram.error import BadRequest

from app_config import AppConfig
from state import BotState, QuizState 
from data_manager import DataManager
from modules.category_manager import CategoryManager
from modules.score_manager import ScoreManager
from modules.quiz_engine import QuizEngine
from .classic_persistence import ClassicPersistenceMixin
from utils import get_current_utc_time, schedule_job_unique, escape_markdown_v2, is_user_admin_in_update
from modules.telegram_utils import safe_send_message, format_error_message, is_formatting_error

logger = logging.getLogger(__name__)

(CFG_QUIZ_OPTIONS, CFG_QUIZ_NUM_QS, CFG_QUIZ_INTERVAL_OPTIONS, CFG_QUIZ_INTERVAL_INPUT, CFG_QUIZ_OPEN_PERIOD_OPTIONS, CFG_QUIZ_OPEN_PERIOD_INPUT) = map(str, range(6))

CB_QCFG_ = "qcfg_"
CB_QCFG_NUM_MENU = f"{CB_QCFG_}num_menu"
CB_QCFG_NUM_VAL = f"{CB_QCFG_}num_val"
CB_QCFG_CAT_MENU = f"{CB_QCFG_}cat_menu"
CB_QCFG_CAT_VAL = f"{CB_QCFG_}cat_val"
CB_QCFG_ANNOUNCE = f"{CB_QCFG_}announce"
CB_QCFG_INTERVAL = f"{CB_QCFG_}interval"
CB_QCFG_INTERVAL_OPT = f"{CB_QCFG_}interval_opt"
CB_QCFG_OPEN_PERIOD = f"{CB_QCFG_}open_period"
CB_QCFG_OPEN_PERIOD_OPT = f"{CB_QCFG_}open_period_opt"
CB_QCFG_START = f"{CB_QCFG_}start"
CB_QCFG_CANCEL = f"{CB_QCFG_}cancel"
CB_QCFG_BACK = f"{CB_QCFG_}back_to_main_opts"
CB_QCFG_NOOP = f"{CB_QCFG_}noop"
CB_QCFG_CAT_POOL_MODE = f"{CB_QCFG_}cat_pool_mode"
CB_QCFG_CAT_POOL_SELECT = f"{CB_QCFG_}cat_pool_select"

DELAY_BEFORE_SESSION_MESSAGES_DELETION_SECONDS = 180   # 3 минуты для служебных сообщений
DELAY_BEFORE_POLL_SOLUTION_DELETION_SECONDS = 120      # 2 минуты для опросов (постепенное удаление)
DELAY_BEFORE_RESULTS_DELETION_SECONDS = 180            # 3 минуты для результатов (дольше всего) 

class QuizManager(ClassicPersistenceMixin):
    def __init__(
        self, app_config: AppConfig, state: BotState, category_manager: CategoryManager,
        score_manager: ScoreManager, data_manager: DataManager, application: Application
    ):
        self.app_config = app_config
        self.state = state
        self.category_manager = category_manager
        self.score_manager = score_manager
        self.data_manager = data_manager
        self.application = application
        self.quiz_engine = QuizEngine(state=self.state, app_config=self.app_config, data_manager=self.data_manager)
        self.moscow_tz = pytz.timezone('Europe/Moscow')
        # Защита от параллельных вызовов _send_next_question для одного чата
        self._send_question_locks: Dict[int, asyncio.Lock] = {}
        logger.debug(f"QuizManager initialized. Command for quiz: '/{self.app_config.commands.quiz}'")

    async def _get_effective_quiz_params(self, chat_id: int, num_questions_override: Optional[int] = None) -> Dict[str, Any]:
        chat_s = await self.data_manager.get_chat_settings_async(chat_id)
        default_chat_settings_global = self.app_config.default_chat_settings
        num_q: int
        if num_questions_override is not None:
            num_q = max(1, min(num_questions_override, self.app_config.max_questions_per_session))
        else:
            num_q = chat_s.get("default_num_questions", default_chat_settings_global.get("default_num_questions", 10))

        if num_q == 1:
            quiz_type_key_for_params_lookup = "single"
        else:
            quiz_type_key_for_params_lookup = chat_s.get("default_quiz_type")
            if not quiz_type_key_for_params_lookup:
                 quiz_type_key_for_params_lookup = default_chat_settings_global.get("default_quiz_type", "session")

        type_cfg_for_params = self.app_config.quiz_types_config.get(quiz_type_key_for_params_lookup, {})

        # Определяем интервал: сначала из настроек чата, затем из конфигурации типа
        interval_seconds = chat_s.get("default_interval_seconds", type_cfg_for_params.get("default_interval_seconds"))
        
        # Определяем режим на основе интервала
        if num_q == 1:
            quiz_mode = "single_question"
        elif interval_seconds and interval_seconds > 0:
            quiz_mode = "serial_interval"
        else:
            quiz_mode = "serial_immediate"
        
        # НОВОЕ: Получаем настройки квизов из чата или используем дефолтные
        quiz_settings = chat_s.get("quiz_settings", {})
        default_quiz_settings = default_chat_settings_global.get("quiz_settings", {})
        
        return {
            "quiz_type_key": quiz_type_key_for_params_lookup,
            "quiz_mode": quiz_mode,
            "num_questions": num_q,
            "open_period_seconds": chat_s.get("default_open_period_seconds", type_cfg_for_params.get("default_open_period_seconds", default_chat_settings_global.get("default_open_period_seconds",30))),
            "announce_quiz": chat_s.get("default_announce_quiz", type_cfg_for_params.get("announce", default_chat_settings_global.get("default_announce_quiz", False))),
            "announce_delay_seconds": chat_s.get("default_announce_delay_seconds", type_cfg_for_params.get("default_announce_delay_seconds", default_chat_settings_global.get("default_announce_delay_seconds", 5))),
            "interval_seconds": interval_seconds,
            "enabled_categories_chat": chat_s.get("enabled_categories"),
            "disabled_categories_chat": chat_s.get("disabled_categories", []),
            # НОВОЕ: Настройки квизов
            "quiz_categories_mode": quiz_settings.get("categories_mode", default_quiz_settings.get("default_categories_mode", "all")),
            "quiz_num_random_categories": quiz_settings.get("default_num_random_categories", default_quiz_settings.get("default_num_random_categories", 3)),
            "quiz_specific_categories": quiz_settings.get("default_specific_categories", default_quiz_settings.get("default_specific_categories", [])),
            "quiz_interval_seconds": quiz_settings.get("default_interval_seconds", default_quiz_settings.get("default_interval_seconds", 30)),
            "quiz_open_period_seconds": quiz_settings.get("default_open_period_seconds", default_quiz_settings.get("default_open_period_seconds", 30)),
            "quiz_announce_quiz": quiz_settings.get("default_announce_quiz", default_quiz_settings.get("default_announce_quiz", False)),
            "quiz_announce_delay_seconds": quiz_settings.get("default_announce_delay_seconds", default_quiz_settings.get("default_announce_delay_seconds", 5)),
        }

    async def _initiate_quiz_session(
        self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, initiated_by_user: Optional[TelegramUser],
        quiz_type: str, quiz_mode: str, num_questions: int, open_period_seconds: int,
        announce: bool, announce_delay_seconds: int,
        category_names_for_quiz: Optional[List[str]] = None,
        is_random_categories_mode: bool = False,
        interval_seconds: Optional[int] = None,
        original_command_message_id: Optional[int] = None,
        interactive_start_message_id: Optional[int] = None
    ):
        logger.info(f"НАЧАЛО _initiate_quiz_session: Чат {chat_id}, Тип: {quiz_type}, Режим: {quiz_mode}, NQ: {num_questions}")
        if self._pg_sessions:
            return await self._start_platform_classic(
                context=context,
                chat_id=chat_id,
                initiated_by_user=initiated_by_user,
                quiz_type=quiz_type,
                num_questions=num_questions,
                open_period_seconds=open_period_seconds,
                announce=announce,
                announce_delay_seconds=announce_delay_seconds,
                category_names_for_quiz=category_names_for_quiz,
                is_random_categories_mode=is_random_categories_mode,
                interval_seconds=interval_seconds,
            )

        active_quiz = self.state.get_active_quiz(chat_id)
        if active_quiz and not active_quiz.is_stopping:
            logger.warning(f"_initiate_quiz_session: Викторина уже активна в чате {chat_id}.")
            if initiated_by_user:
                already_running_msg = await safe_send_message(
                    bot=context.bot,
                    chat_id=chat_id,
                    text=escape_markdown_v2(f"Викторина уже идет. Остановите текущую (`/{self.app_config.commands.stop_quiz}`)."),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                # Добавляем системное сообщение в автоудаление
                if already_running_msg:
                    self.state.add_message_for_deletion(chat_id, already_running_msg.message_id, delay_seconds=30)
            return

        cat_mode_for_get_questions: str
        if is_random_categories_mode:
            cat_mode_for_get_questions = "random_from_pool"
        elif category_names_for_quiz:
            cat_mode_for_get_questions = "specific_only"
        else:
            cat_mode_for_get_questions = "random_from_pool"

        logger.debug(f"_initiate_quiz_session: Получение вопросов. Режим для get_questions: {cat_mode_for_get_questions}, Исходные запрашиваемые категории: {category_names_for_quiz}")
        if self._pg_sessions:
            await self.category_manager.refresh_postgres_statistics()
            # Reload the static bank before selection; running games own snapshots.
            await self.data_manager.load_questions_async()
        questions_for_session = self.category_manager.get_questions(
            num_questions_needed=num_questions,
            chat_id=chat_id,
            allowed_specific_categories=category_names_for_quiz if cat_mode_for_get_questions == "specific_only" else None,
            mode=cat_mode_for_get_questions
        )
        logger.debug(f"_initiate_quiz_session: Получено {len(questions_for_session)} вопросов.")

        # Определяем множество использованных категорий для анонса
        used_categories_set = set()
        for question in questions_for_session:
            if 'current_category_name_for_quiz' in question:
                used_categories_set.add(question['current_category_name_for_quiz'])
            elif 'original_category' in question:
                used_categories_set.add(question['original_category'])

        actual_num_questions_obtained = len(questions_for_session)
        if actual_num_questions_obtained == 0:
            msg_no_q = "Не удалось подобрать вопросы для викторины. Проверьте настройки категорий или попробуйте позже."
            logger.warning(f"_initiate_quiz_session: {msg_no_q} (Чат: {chat_id}, NQ: {num_questions}, Режим кат: {cat_mode_for_get_questions}, Список кат: {category_names_for_quiz})")
            if initiated_by_user:
                await safe_send_message(
            bot=context.bot,
            chat_id=chat_id,
            text=escape_markdown_v2(msg_no_q),
            parse_mode=ParseMode.MARKDOWN_V2
        )
            if interactive_start_message_id:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=interactive_start_message_id)
                    logger.debug(f"Сообщение о запуске ({interactive_start_message_id}) удалено, т.к. викторина не стартовала.")
                except Exception as e_del_launch_msg_fail:
                    logger.warning(f"Не удалось удалить сообщение о запуске ({interactive_start_message_id}) при неудачном старте викторины: {e_del_launch_msg_fail}")
            return

        if actual_num_questions_obtained < num_questions:
            logger.info(f"_initiate_quiz_session: Запрошено {num_questions}, доступно {actual_num_questions_obtained}. Викторина будет с {actual_num_questions_obtained} вопросами. Чат: {chat_id}")
            num_questions = actual_num_questions_obtained

        # СТАТИСТИКА КАТЕГОРИЙ БУДЕТ ОБНОВЛЕНА В КОНЦЕ ВИКТОРИНЫ
        # (после завершения всех вопросов, один раз за сессию)


        user_id_int_for_state: Optional[int] = int(initiated_by_user.id) if initiated_by_user else None
        
        # Получаем эффективный интервал из параметров
        effective_interval = interval_seconds
        
        # Получаем эффективное время ответа: сначала из параметров, затем из настроек чата
        effective_open_period = open_period_seconds
        if effective_open_period is None:
            effective_params = await self._get_effective_quiz_params(chat_id, num_questions)
            effective_open_period = effective_params.get('open_period_seconds', 30)
        
        # Определяем режим викторины на основе интервала
        if effective_interval and effective_interval > 0:
            final_quiz_mode = "serial_interval"
        else:
            final_quiz_mode = "serial_immediate"
        
        logger.debug(f"DEBUG: Режим викторины: {final_quiz_mode}, интервал: {effective_interval}")
        
        current_quiz_state_instance = QuizState(
            chat_id=chat_id, quiz_type=quiz_type, quiz_mode=final_quiz_mode,
            questions=questions_for_session, num_questions_to_ask=num_questions,
            open_period_seconds=effective_open_period, created_by_user_id=user_id_int_for_state,
            original_command_message_id=original_command_message_id,
            interval_seconds=effective_interval, quiz_start_time=get_current_utc_time()
        )

        if self._pg_sessions:
            await self._checkpoint_classic(current_quiz_state_instance, create=True)
            self.state.add_active_quiz(chat_id, current_quiz_state_instance)

        if interactive_start_message_id:
            current_quiz_state_instance.message_ids_to_delete.add(interactive_start_message_id)
            logger.debug(f"Сообщение о запуске из интерактива ({interactive_start_message_id}) добавлено в список на удаление (служебные).")

        if announce:
            announce_text_parts = []
            if quiz_type == "daily":
                greeting = ""
                try:
                    current_time_msk = dt.datetime.now(self.moscow_tz)
                    current_hour_msk = current_time_msk.hour

                    if 5 <= current_hour_msk <= 11: greeting = "Доброе утро☀️"
                    elif 12 <= current_hour_msk <= 16: greeting = "Добрый день🌞"
                    elif 17 <= current_hour_msk <= 22: greeting = "Добрый вечер🌙"
                    else: greeting = "Доброй ночи✨"
                    announce_text_parts.append(escape_markdown_v2(f"{greeting}!"))
                except Exception as e_greeting:
                    logger.warning(f"Не удалось определить приветствие по времени для ежедневной викторины: {e_greeting}")
                    announce_text_parts.append(escape_markdown_v2("Привет!"))

                announce_text_parts.append(escape_markdown_v2("Начинается ежедневная викторина."))
                if used_categories_set:
                    announce_text_parts.append(escape_markdown_v2(f"Темы сегодня: {', '.join(sorted(list(used_categories_set)))}."))
                else:
                    announce_text_parts.append(escape_markdown_v2("Темы будут сюрпризом!"))
                if announce_delay_seconds > 0:
                    announce_text_parts.append(f"Старт через {escape_markdown_v2(str(announce_delay_seconds))} сек\\!")
            else:
                if initiated_by_user:
                    announce_text_parts.append(f"{escape_markdown_v2(initiated_by_user.first_name)} запускает викторину\\!")
                if announce_delay_seconds > 0:
                    announce_text_parts.append(f"🔔 Викторина начнется через {escape_markdown_v2(str(announce_delay_seconds))} сек\\!")
                elif not interactive_start_message_id and not initiated_by_user : # Для не-daily, не-интерактивного, немедленного старта без user_id (не должно быть)
                    announce_text_parts.append(escape_markdown_v2("🏁 Викторина начинается!"))

            full_announce_text = " ".join(announce_text_parts)
            if full_announce_text.strip():
                try:
                    msg = await safe_send_message(
            bot=context.bot,
            chat_id=chat_id,
            text=full_announce_text,
            parse_mode=ParseMode.MARKDOWN_V2
        )
                    current_quiz_state_instance.announce_message_id = msg.message_id
                    current_quiz_state_instance.message_ids_to_delete.add(msg.message_id)
                    # Добавляем в глобальный список для периодической очистки
                    self.state.add_message_for_deletion(chat_id, msg.message_id)
                except Exception as e_announce:
                    logger.error(f"Ошибка отправки анонса (delay: {announce_delay_seconds > 0}) в чат {chat_id}: {e_announce}")

                    # Автоматическое отключение рассылки при блокировке или недоступности чата
                    error_message = str(e_announce).lower()
                    if quiz_type == "daily" and ("blocked" in error_message or "not found" in error_message or "forbidden" in error_message):
                        logger.warning(f"⚠️ Обнаружена блокировка/недоступность чата {chat_id}. Автоматически отключаю ежедневную рассылку.")
                        await self.data_manager.disable_daily_quiz_for_chat(
                            chat_id,
                            reason="blocked" if "blocked" in error_message else "not_found"
                        )
            else:
                logger.debug(f"Текст анонса пуст для чата {chat_id}, отправка пропущена.")

            if announce_delay_seconds > 0:
                self.state.add_active_quiz(chat_id, current_quiz_state_instance)
                logger.info(f"_initiate_quiz_session: QuizState создан и добавлен для чата {chat_id}. Тип: {quiz_type}. Ожидание {announce_delay_seconds} сек...")
                await asyncio.sleep(announce_delay_seconds)
                logger.debug(f"Ожидание завершено для чата {chat_id}.")
                quiz_state_after_delay_check = self.state.get_active_quiz(chat_id)
                if not quiz_state_after_delay_check or quiz_state_after_delay_check.is_stopping or quiz_state_after_delay_check != current_quiz_state_instance:
                    logger.info(f"Викторина в чате {chat_id} была остановлена/заменена во время задержки анонса. Запуск отменен.")
                    if self.state.get_active_quiz(chat_id) == current_quiz_state_instance:
                        self.state.remove_active_quiz(chat_id) 
                    return
            else: 
                self.state.add_active_quiz(chat_id, current_quiz_state_instance)
                logger.info(f"_initiate_quiz_session: QuizState (немедленный анонс или без анонса если текст пуст) создан и добавлен для чата {chat_id}. Тип: {quiz_type}")
        else: 
            self.state.add_active_quiz(chat_id, current_quiz_state_instance)
            logger.info(f"_initiate_quiz_session: QuizState (без анонса) создан и добавлен для чата {chat_id}. Тип: {quiz_type}")

        logger.info(f"_initiate_quiz_session: Переход к отправке первого вопроса для чата {chat_id}.")
        await self._send_next_question(context, chat_id)

    async def _start_platform_classic(
        self, *, context, chat_id, initiated_by_user, quiz_type,
        num_questions, open_period_seconds, announce,
        announce_delay_seconds, category_names_for_quiz,
        is_random_categories_mode, interval_seconds,
    ):
        """Thin Telegram adapter for the shared Classic application service."""
        from application.classic import ClassicApplicationService
        from application.classic_selection import select_classic_questions
        from storage.classic_sessions import ClassicSessionConflict

        database = self._pg_sessions.database
        try:
            async with database.transaction() as session:
                questions = await select_classic_questions(
                    session,
                    chat_id=chat_id,
                    count=num_questions,
                    defaults=self.app_config.default_chat_settings,
                    category_names=category_names_for_quiz,
                    random_categories=is_random_categories_mode or not category_names_for_quiz,
                )
                if not questions:
                    raise ValueError(
                        'Не удалось подобрать вопросы. Проверьте настройки категорий.'
                    )
                user_id = initiated_by_user.id if initiated_by_user else None
                name = initiated_by_user.full_name if initiated_by_user else None
                game = await ClassicApplicationService(
                    database, session,
                    rules=self.score_manager._classic_scoring_rules(),
                ).start(
                    chat_id=chat_id,
                    user_id=user_id,
                    display_name=name,
                    questions=questions,
                    quiz_type=quiz_type,
                    open_seconds=open_period_seconds,
                    interval_seconds=max(0, interval_seconds or 0),
                    start_delay_seconds=announce_delay_seconds if announce else 0,
                )
        except (ClassicSessionConflict, ValueError) as error:
            if initiated_by_user:
                await safe_send_message(
                    bot=context.bot,
                    chat_id=chat_id,
                    text=escape_markdown_v2(str(error)),
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            return None
        if announce:
            actor = initiated_by_user.first_name if initiated_by_user else 'Филиныч'
            delay = announce_delay_seconds if announce_delay_seconds > 0 else 0
            text = f'{actor} запускает викторину!'
            if delay:
                text += f' Первый вопрос появится через {delay} сек.'
            await safe_send_message(
                bot=context.bot,
                chat_id=chat_id,
                text=escape_markdown_v2(text),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        logger.info(
            'Classic platform game %s created for chat %s', game.get('game_id'), chat_id
        )
        return game

    async def _send_next_question(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int,
                                  *, expected_session_id=None, expected_question_index=None):
        # Защита от параллельных вызовов для одного чата
        if chat_id not in self._send_question_locks:
            self._send_question_locks[chat_id] = asyncio.Lock()
        
        async with self._send_question_locks[chat_id]:
            if await self._discard_interrupted_classic(chat_id):
                return
            logger.debug(f"НАЧАЛО _send_next_question для чата {chat_id}.")
            quiz_state = self.state.get_active_quiz(chat_id)

            if not quiz_state or quiz_state.is_stopping:
                logger.warning(f"_send_next_question: Викторина неактивна или останавливается для чата {chat_id}.")
                return

            if self._pg_sessions and (
                (expected_session_id is not None and quiz_state.session_id != expected_session_id)
                or (expected_question_index is not None and quiz_state.current_question_index != expected_question_index)
            ):
                return  # Recheck after waiting for an in-flight send, not only at job entry.

            if quiz_state.current_question_index >= quiz_state.num_questions_to_ask:
                logger.info(f"_send_next_question: Все {quiz_state.num_questions_to_ask} вопросов для чата {chat_id} уже отправлены.")
                return

            # Дополнительная проверка: убеждаемся, что вопрос с этим индексом еще не отправлялся
            # Проверяем по poll_id для текущего индекса
            expected_q_index = quiz_state.current_question_index
            for poll_id in list(quiz_state.active_poll_ids_in_session):
                poll_data = self.state.get_current_poll_data(poll_id)
                if poll_data and poll_data.get("question_session_index") == expected_q_index:
                    logger.warning(f"_send_next_question: Вопрос с индексом {expected_q_index} уже был отправлен (poll_id: {poll_id}). Пропуск дубликата.")
                    return

            question_data = quiz_state.get_current_question_data()
            if not question_data:
                error_msg_text = "Ошибка получения данных вопроса."
                logger.error(f"_send_next_question: {error_msg_text} Индекс: {quiz_state.current_question_index}, чат: {chat_id}. Завершение.")
                await self._finalize_quiz_session(context, chat_id, error_occurred=True, error_message=error_msg_text, _send_locked=True)
                return

            logger.info(f"_send_next_question: Отправка вопроса {quiz_state.current_question_index + 1}/{quiz_state.num_questions_to_ask} в чате {chat_id}.")

            is_last_q_in_this_session = (quiz_state.current_question_index == quiz_state.num_questions_to_ask - 1)
            q_num_display = quiz_state.current_question_index + 1
            title_prefix_for_poll_unescaped: str
            if quiz_state.quiz_type == "single": title_prefix_for_poll_unescaped = "Вопрос"
            elif quiz_state.quiz_type == "daily": title_prefix_for_poll_unescaped = f"Ежедневный вопрос {q_num_display}/{quiz_state.num_questions_to_ask}"
            else: title_prefix_for_poll_unescaped = f"Вопрос {q_num_display}/{quiz_state.num_questions_to_ask}"

            current_category_name_display_unescaped = question_data.get('current_category_name_for_quiz', question_data.get('original_category'))

            if self._pg_sessions:
                quiz_state.storage_phase = "sending"
                quiz_state.next_question_at = None
                await self._checkpoint_classic(quiz_state)
                if quiz_state.is_stopping or self.state.get_active_quiz(chat_id) is not quiz_state:
                    return

            sent_poll_id = await self.quiz_engine.send_quiz_poll(
                context, chat_id, question_data,
                poll_title_prefix=title_prefix_for_poll_unescaped,
                open_period_seconds=quiz_state.open_period_seconds,
                quiz_type=quiz_state.quiz_type,
                is_last_question=is_last_q_in_this_session,
                question_session_index=quiz_state.current_question_index,
                current_category_name=current_category_name_display_unescaped if current_category_name_display_unescaped else None,
                persist_poll=(lambda poll_id: self._confirm_classic_poll(quiz_state, poll_id)) if self._pg_sessions else None,
                before_send=lambda: self._classic_send_allowed(quiz_state),
            )

            if sent_poll_id:
                quiz_state_after_poll_send = self.state.get_active_quiz(chat_id)
                if not quiz_state_after_poll_send or quiz_state_after_poll_send.is_stopping or quiz_state_after_poll_send != quiz_state:
                    logger.warning(f"_send_next_question: Викторина для чата {chat_id} изменилась/остановилась во время отправки опроса. Отмена дальнейших действий для этого вызова.")
                    return

                quiz_state.active_poll_ids_in_session.add(sent_poll_id)
                quiz_state.latest_poll_id_sent = sent_poll_id
                if not self._pg_sessions:
                    quiz_state.progression_triggered_for_poll[sent_poll_id] = False

                poll_data_from_bot_state = self.state.get_current_poll_data(sent_poll_id)
                if not poll_data_from_bot_state:
                    error_msg_poll_data = "Внутренняя ошибка: потеряны данные опроса при создании (сразу после send_quiz_poll)."
                    logger.error(f"_send_next_question: {error_msg_poll_data} Poll ID: {sent_poll_id}, чат: {chat_id}.")
                    await self._finalize_quiz_session(context, chat_id, error_occurred=True, error_message=error_msg_poll_data, _send_locked=True)
                    return

                job_name_for_this_poll_end = f"poll_end_chat_{chat_id}_poll_{sent_poll_id}"
                poll_data_from_bot_state["job_poll_end_name"] = job_name_for_this_poll_end

                schedule_job_unique(
                    self.application.job_queue,
                    job_name=job_name_for_this_poll_end,
                    callback=self._handle_poll_end_job,
                    when=timedelta(seconds=quiz_state.open_period_seconds + self.app_config.job_grace_period_seconds),
                    data={"chat_id": chat_id, "ended_poll_id": sent_poll_id, "session_id": quiz_state.session_id}
                )

                if not self._pg_sessions:
                    quiz_state.current_question_index += 1
                logger.debug(f"_send_next_question: Индекс вопроса в чате {chat_id} увеличен до {quiz_state.current_question_index}.")

                # Планируем следующий вопрос, если есть интервал и это не последний вопрос
                if (quiz_state.quiz_mode == "serial_interval" and
                    quiz_state.interval_seconds is not None and
                    quiz_state.interval_seconds > 0 and
                    quiz_state.current_question_index < quiz_state.num_questions_to_ask):

                    delay_seconds = quiz_state.interval_seconds
                    job_name = f"delayed_next_q_after_send_chat_{chat_id}_qidx_{quiz_state.current_question_index}"
                    quiz_state.next_question_job_name = job_name
                    schedule_job_unique(
                        self.application.job_queue,
                        job_name=job_name,
                        callback=self._trigger_next_question_job_after_interval,
                        when=timedelta(seconds=delay_seconds),
                        data={"chat_id": chat_id, "expected_q_index_at_trigger": quiz_state.current_question_index, "session_id": quiz_state.session_id}
                    )
                    logger.info(f"Следующий вопрос (индекс {quiz_state.current_question_index}) будет отправлен через {delay_seconds} сек (режим serial_interval).")
            else:
                error_msg_text_send_poll = "Ошибка отправки опроса через Telegram API (QuizEngine.send_quiz_poll вернул None)."
                logger.error(f"_send_next_question: {error_msg_text_send_poll} Вопрос: {quiz_state.current_question_index}, чат: {chat_id}.")
                await self._finalize_quiz_session(context, chat_id, error_occurred=True, error_message=error_msg_text_send_poll, _send_locked=True)

            logger.debug(f"ЗАВЕРШЕНИЕ _send_next_question для чата {chat_id} (вопрос {quiz_state.current_question_index-1 if quiz_state else 'N/A'} отправлен).")

    async def _handle_early_answer_for_session(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, answered_poll_id: str):
        if await self._discard_interrupted_classic(chat_id):
            return
        logger.info(f"Обработка ответа на опрос {answered_poll_id} в чате {chat_id}.")
        quiz_state = self.state.get_active_quiz(chat_id)

        if not quiz_state or quiz_state.is_stopping:
            logger.debug(f"Ответ на опрос {answered_poll_id} проигнорирован: викторина неактивна или останавливается.")
            return

        if self._pg_sessions and answered_poll_id != quiz_state.latest_poll_id_sent:
            return  # An answer to an older poll must not advance a newer question.

        if quiz_state.progression_triggered_for_poll.get(answered_poll_id, False):
            logger.debug(f"Ответ на опрос {answered_poll_id}: переход к следующему вопросу уже был инициирован ранее для этого опроса.")
            return

        quiz_state.progression_triggered_for_poll[answered_poll_id] = True

        poll_data_in_state = self.state.get_current_poll_data(answered_poll_id)
        if poll_data_in_state:
            poll_data_in_state["next_q_triggered_by_answer"] = True
            logger.debug(f"Флаг next_q_triggered_by_answer установлен в True для poll_id {answered_poll_id}")
        else:
            logger.warning(f"Не найдены данные для poll_id {answered_poll_id} в self.state.current_polls при попытке установить флаг next_q_triggered_by_answer.")

        if self._pg_sessions:
            quiz_state.next_question_at = (get_current_utc_time() + timedelta(seconds=quiz_state.interval_seconds or 0)).isoformat()
            await self._checkpoint_classic(quiz_state)
            if quiz_state.is_stopping or self.state.get_active_quiz(chat_id) is not quiz_state:
                return

        logger.info(f"Первый значащий ответ на опрос {answered_poll_id} (чат {chat_id}). Инициируется отправка следующего вопроса / планирование.")

        if quiz_state.current_question_index < quiz_state.num_questions_to_ask:
            if quiz_state.next_question_job_name: 
                jobs = self.application.job_queue.get_jobs_by_name(quiz_state.next_question_job_name)
                for job in jobs: job.schedule_removal()
                logger.debug(f"Отменена предыдущая задача отложенной отправки {quiz_state.next_question_job_name}.")
                quiz_state.next_question_job_name = None

            if quiz_state.quiz_mode == "serial_interval" and quiz_state.interval_seconds is not None and quiz_state.interval_seconds > 0:
                delay_seconds = quiz_state.interval_seconds
                job_name = f"delayed_next_q_after_answer_chat_{chat_id}_qidx_{quiz_state.current_question_index}"
                quiz_state.next_question_job_name = job_name
                schedule_job_unique(
                    self.application.job_queue,
                    job_name=job_name,
                    callback=self._trigger_next_question_job_after_interval,
                    when=timedelta(seconds=delay_seconds),
                    data={"chat_id": chat_id, "expected_q_index_at_trigger": quiz_state.current_question_index, "session_id": quiz_state.session_id}
                )
                logger.info(f"Следующий вопрос (индекс {quiz_state.current_question_index}) будет отправлен через {delay_seconds} сек (режим serial_interval).")
            else: 
                logger.info(f"Режим '{quiz_state.quiz_mode}', немедленная отправка следующего вопроса (индекс {quiz_state.current_question_index}).")
                await self._send_next_question(context, chat_id, expected_session_id=quiz_state.session_id,
                                               expected_question_index=quiz_state.current_question_index)
        else:
            logger.info(f"Все вопросы ({quiz_state.num_questions_to_ask}) уже были отправлены. Ответ на {answered_poll_id} не триггерит новые вопросы.")

    async def _trigger_next_question_job_after_interval(self, context: ContextTypes.DEFAULT_TYPE):
        if not context.job or not isinstance(context.job.data, dict): return

        chat_id: Optional[int] = context.job.data.get("chat_id")
        expected_q_idx: Optional[int] = context.job.data.get("expected_q_index_at_trigger")

        if chat_id is None:
            logger.error(f"_trigger_next_question_job_after_interval: chat_id отсутствует. Job: {context.job.name if context.job else 'N/A'}")
            return

        quiz_state = self.state.get_active_quiz(chat_id)
        if not quiz_state or quiz_state.is_stopping:
            logger.info(f"_trigger_next_question_job_after_interval: Викторина для чата {chat_id} неактивна или останавливается. Пропуск.")
            return

        if not self._valid_classic_job(context, chat_id):
            return
        if await self._discard_interrupted_classic(chat_id):
            return
        if expected_q_idx is not None and quiz_state.current_question_index != expected_q_idx:
            logger.warning(f"_trigger_next_question_job_after_interval (чат {chat_id}): Ожидаемый индекс вопроса {expected_q_idx} не совпадает с текущим {quiz_state.current_question_index}. Пропуск отправки.")
            return

        if quiz_state.next_question_job_name == (context.job.name if context.job else None):
            quiz_state.next_question_job_name = None 

        logger.info(f"Сработала задача отложенной отправки следующего вопроса для чата {chat_id}. Job: {context.job.name if context.job else 'N/A'}.")
        await self._send_next_question(context, chat_id, expected_session_id=quiz_state.session_id,
                                      expected_question_index=expected_q_idx)

    async def _handle_poll_end_job(self, context: ContextTypes.DEFAULT_TYPE):
        if not context.job or not isinstance(context.job.data, dict):
            logger.error("_handle_poll_end_job: context.job или context.job.data некорректны.")
            return

        job_data: Dict[str, Any] = context.job.data
        chat_id: Optional[int] = job_data.get("chat_id")
        ended_poll_id: Optional[str] = job_data.get("ended_poll_id")

        if chat_id is None or ended_poll_id is None:
            logger.error(f"_handle_poll_end_job: chat_id или ended_poll_id отсутствуют. Data: {job_data}")
            return

        if not self._valid_classic_job(context, chat_id):
            return
        logger.info(f"Сработал таймаут для poll_id {ended_poll_id} в чате {chat_id}. Job: {context.job.name}")
        if await self._discard_interrupted_classic(chat_id):
            return

        poll_info_before_removal = self.state.get_current_poll_data(ended_poll_id)
        
        # Защита от повторной обработки: проверяем, что опрос еще существует в state
        # Если его нет, значит он уже был обработан
        if not poll_info_before_removal:
            logger.debug(f"_handle_poll_end_job: Опрос {ended_poll_id} уже был обработан или удален. Пропускаем повторную обработку.")
            return
        
        quiz_state = self.state.get_active_quiz(chat_id)
        sent_solution_msg_id = await self.quiz_engine.send_solution_if_available(
            context, chat_id, ended_poll_id,
            persist_solution=(lambda: self._checkpoint_classic(quiz_state)) if self._pg_sessions else None,
            before_send=(lambda: self._classic_send_allowed(quiz_state)) if quiz_state else None,
        )
        if self._pg_sessions and (self.state.get_active_quiz(chat_id) is not quiz_state or quiz_state.is_stopping):
            if sent_solution_msg_id:
                await self._queue_classic_messages(chat_id, [sent_solution_msg_id])
            return

        # НАКОПЛЕНИЕ message_ids для батч-удаления в конце викторины
        if poll_info_before_removal and quiz_state:
            ended_poll_message_id = poll_info_before_removal.get("message_id")
            if ended_poll_message_id:
                quiz_state.poll_and_solution_message_ids.append({
                    "poll_msg_id": ended_poll_message_id,
                    "solution_msg_id": sent_solution_msg_id
                })
                logger.debug(f"Poll msg {ended_poll_message_id} and solution msg {sent_solution_msg_id} for poll {ended_poll_id} added to delayed delete list for chat {chat_id}.")
            else:
                logger.warning(f"_handle_poll_end_job: message_id не найден в poll_info_before_removal для poll_id {ended_poll_id}, чат {chat_id}. Не добавлено в список на удаление.")
        elif not poll_info_before_removal:
             logger.warning(f"_handle_poll_end_job: poll_info_before_removal is None для poll_id {ended_poll_id}, чат {chat_id}. Не добавлено в список на удаление.")

        if self._pg_sessions and quiz_state:
            quiz_state.poll_history[ended_poll_id] = dict(poll_info_before_removal)
        self.state.remove_current_poll(ended_poll_id)

        if not quiz_state: 
            logger.info(f"_handle_poll_end_job: Викторина для чата {chat_id} не найдена (возможно, уже завершена).")
            return

        next_q_was_triggered_by_answer = False
        if poll_info_before_removal:
            next_q_was_triggered_by_answer = poll_info_before_removal.get("next_q_triggered_by_answer", False)
        else:
            logger.warning(f"_handle_poll_end_job: Не удалось получить poll_info_before_removal (повторно) для poll_id {ended_poll_id} в чате {chat_id}.")

        if quiz_state.is_stopping:
            logger.info(f"_handle_poll_end_job: Викторина для чата {chat_id} в процессе остановки.")
            quiz_state.active_poll_ids_in_session.discard(ended_poll_id)
            quiz_state.progression_triggered_for_poll.pop(ended_poll_id, None)
            if not quiz_state.active_poll_ids_in_session and quiz_state.is_stopping:
                 logger.info(f"Это был последний активный опрос ({ended_poll_id}) в останавливаемой викторине. Финализация инициируется.")
                 await self._finalize_quiz_session(context, chat_id, was_stopped=True)
            return

        quiz_state.active_poll_ids_in_session.discard(ended_poll_id)
        quiz_state.progression_triggered_for_poll.pop(ended_poll_id, None)

        await self._checkpoint_classic(quiz_state)

        if quiz_state.current_question_index < quiz_state.num_questions_to_ask:
            if not next_q_was_triggered_by_answer and (not self._pg_sessions or ended_poll_id == quiz_state.latest_poll_id_sent):
                logger.info(f"Таймаут для опроса {ended_poll_id} (чат {chat_id}). Досрочный ответ НЕ инициировал переход. Запуск следующего вопроса.")
                if quiz_state.next_question_job_name: 
                    jobs = self.application.job_queue.get_jobs_by_name(quiz_state.next_question_job_name)
                    for job in jobs: job.schedule_removal()
                    quiz_state.next_question_job_name = None
                await self._send_next_question(context, chat_id, expected_session_id=quiz_state.session_id,
                                               expected_question_index=quiz_state.current_question_index)
            else:
                logger.info(f"Таймаут для опроса {ended_poll_id} (чат {chat_id}). Переход к следующему вопросу уже был инициирован досрочным ответом. Дополнительная отправка из _handle_poll_end_job не требуется.")
        elif not quiz_state.active_poll_ids_in_session: 
            logger.info(f"Все вопросы отправлены ({quiz_state.current_question_index}/{quiz_state.num_questions_to_ask}) и все опросы ({ended_poll_id} был последним активным) завершены. Финализация для чата {chat_id}.")
            await self._finalize_quiz_session(context, chat_id)
        else:
            logger.info(f"Опрос {ended_poll_id} завершен. В сессии для чата {chat_id} еще есть активные опросы ({len(quiz_state.active_poll_ids_in_session)}) или не все вопросы отправлены. Ожидание.")

    async def _delayed_delete_messages_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Job-функция для отложенного удаления СЛУЖЕБНЫХ сообщений викторины."""
        if not context.job or not isinstance(context.job.data, dict):
            logger.error("_delayed_delete_messages_job: context.job или context.job.data некорректны.")
            return

        chat_id: Optional[int] = context.job.data.get("chat_id")
        message_ids_to_delete_list: Optional[List[int]] = context.job.data.get("message_ids")

        if chat_id is None or message_ids_to_delete_list is None:
            logger.error(f"_delayed_delete_messages_job: chat_id или message_ids отсутствуют. Data: {context.job.data}")
            return

        # ИЗМЕНЕНИЕ: Проверка настройки автоудаления
        chat_settings = await self.data_manager.get_chat_settings_async(chat_id)
        default_auto_delete_from_config = self.app_config.default_chat_settings.get("auto_delete_bot_messages", True)
        auto_delete_enabled = chat_settings.get("auto_delete_bot_messages", default_auto_delete_from_config)

        if not auto_delete_enabled:
            logger.info(f"Автоудаление СЛУЖЕБНЫХ сообщений отключено для чата {chat_id}. Пропуск удаления {len(message_ids_to_delete_list)} сообщений. Job: {context.job.name if context.job else 'N/A'}")
            return
        # КОНЕЦ ИЗМЕНЕНИЯ

        logger.info(f"Запуск отложенного удаления {len(message_ids_to_delete_list)} СЛУЖЕБНЫХ сообщений в чате {chat_id}. Job: {context.job.name if context.job else 'N/A'}")
        for msg_id in message_ids_to_delete_list:
            success = False
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                logger.info(f"Сообщение {msg_id} (служебное) удалено отложенно из чата {chat_id}.")
                success = True
            except BadRequest as e_br_del:
                 if "message to delete not found" in str(e_br_del).lower() or \
                    "message can't be deleted" in str(e_br_del).lower():
                     logger.debug(f"Сообщение {msg_id} (служебное) уже удалено или не может быть удалено (отложенно): {e_br_del}")
                     success = True  # Считаем успешным - сообщения нет
                 else:
                     logger.warning(f"Ошибка BadRequest при отложенном удалении сообщения {msg_id} (служебное) из чата {chat_id}: {e_br_del}")
            except Exception as e_del_delayed:
                logger.warning(f"Не удалось отложенно удалить сообщение {msg_id} (служебное) из чата {chat_id}: {e_del_delayed}")

            # Удаляем из fallback при успехе
            if success:
                self.state.remove_message_from_deletion(chat_id, msg_id)

        logger.info(f"Отложенное удаление СЛУЖЕБНЫХ сообщений в чате {chat_id} завершено.")

    async def _delayed_delete_poll_solution_messages_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Job-функция для отложенного удаления сообщений викторины (опросы, пояснения, результаты)."""
        if not context.job or not isinstance(context.job.data, dict):
            logger.error("_delayed_delete_poll_solution_messages_job: context.job или context.job.data некорректны.")
            return

        chat_id: Optional[int] = context.job.data.get("chat_id")
        message_ids_to_delete_list: Optional[List[int]] = context.job.data.get("message_ids")

        if chat_id is None or message_ids_to_delete_list is None:
            logger.error(f"_delayed_delete_poll_solution_messages_job: chat_id или message_ids отсутствуют. Data: {context.job.data}")
            return
        
        # ИЗМЕНЕНИЕ: Проверка настройки автоудаления
        chat_settings = await self.data_manager.get_chat_settings_async(chat_id)
        default_auto_delete_from_config = self.app_config.default_chat_settings.get("auto_delete_bot_messages", True)
        auto_delete_enabled = chat_settings.get("auto_delete_bot_messages", default_auto_delete_from_config)

        if not auto_delete_enabled:
            logger.info(f"Автоудаление сообщений викторины отключено для чата {chat_id}. Пропуск удаления {len(message_ids_to_delete_list)} сообщений. Job: {context.job.name if context.job else 'N/A'}")
            return
        # КОНЕЦ ИЗМЕНЕНИЯ

        logger.info(f"Запуск отложенного удаления {len(message_ids_to_delete_list)} сообщений викторины в чате {chat_id}. Job: {context.job.name if context.job else 'N/A'}")
        for msg_id in message_ids_to_delete_list:
            success = False
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                logger.info(f"Сообщение викторины {msg_id} удалено отложенно из чата {chat_id}.")
                success = True
            except BadRequest as e_br_del:
                 if "message to delete not found" in str(e_br_del).lower() or \
                    "message can't be deleted" in str(e_br_del).lower():
                     logger.debug(f"Сообщение викторины {msg_id} уже удалено или не может быть удалено (отложенно): {e_br_del}")
                     success = True  # Считаем успешным - сообщения нет
                 else:
                     logger.warning(f"Ошибка BadRequest при отложенном удалении сообщения {msg_id} (викторина) из чата {chat_id}: {e_br_del}")
            except Exception as e_del_delayed:
                logger.warning(f"Не удалось отложенно удалить сообщение {msg_id} (викторина) из чата {chat_id}: {e_del_delayed}")

            # Удаляем из fallback при успехе
            if success:
                self.state.remove_message_from_deletion(chat_id, msg_id)

        logger.info(f"Отложенное удаление сообщений викторины в чате {chat_id} завершено.")

    async def _finalize_quiz_session(
        self, context: ContextTypes.DEFAULT_TYPE, chat_id: int,
        was_stopped: bool = False, error_occurred: bool = False, error_message: Optional[str] = None,
        *, _send_locked=False,
    ):
        if self._pg_sessions and not _send_locked:
            # An acknowledged in-flight poll must be checkpointed before closing.
            expected_quiz = self.state.get_active_quiz(chat_id)
            async with self._send_question_locks.setdefault(chat_id, asyncio.Lock()):
                if expected_quiz is not self.state.get_active_quiz(chat_id):
                    return
                return await self._finalize_quiz_session_impl(context, chat_id, was_stopped, error_occurred, error_message)
        return await self._finalize_quiz_session_impl(context, chat_id, was_stopped, error_occurred, error_message)

    async def _finalize_quiz_session_impl(
        self, context, chat_id, was_stopped=False, error_occurred=False, error_message=None,
    ):
        quiz_state = self.state.get_active_quiz(chat_id)
        if quiz_state and self._pg_sessions:
            quiz_state.is_stopping = True
            quiz_state.storage_phase = "finished"
            await self._checkpoint_classic(quiz_state, status="interrupted" if error_occurred else "stopped" if was_stopped else "completed")
            quiz_state.scores = await self._pg_sessions.scores(chat_id, list(quiz_state.poll_history))
        quiz_state = self.state.remove_active_quiz(chat_id)
        if not quiz_state:
            logger.warning(f"Попытка финализировать викторину для чата {chat_id}, но активной сессии QuizState не найдено.")
            # Очищаем блокировку даже если викторина не найдена
            if not self._pg_sessions:
                self._send_question_locks.pop(chat_id, None)
            return

        escaped_error_message = escape_markdown_v2(error_message) if error_message else None
        logger.info(f"Завершение викторины (тип: {quiz_state.quiz_type}, режим: {quiz_state.quiz_mode}) в чате {chat_id}. Остановлена: {was_stopped}, Ошибка: {error_occurred}, Сообщение: {error_message}")
        
        # Очищаем блокировку отправки вопросов для этого чата
        if not self._pg_sessions:
            self._send_question_locks.pop(chat_id, None)

        job_queue = self.application.job_queue

        if quiz_state.next_question_job_name and job_queue:
            jobs = job_queue.get_jobs_by_name(quiz_state.next_question_job_name)
            for job in jobs: job.schedule_removal()
            quiz_state.next_question_job_name = None

        active_poll_ids_copy = list(quiz_state.active_poll_ids_in_session)
        for poll_id_to_stop in active_poll_ids_copy:
            poll_data = self.state.get_current_poll_data(poll_id_to_stop) 
            if poll_data:
                job_name_to_cancel = poll_data.get("job_poll_end_name")
                if job_name_to_cancel and job_queue:
                    jobs = job_queue.get_jobs_by_name(job_name_to_cancel)
                    for job in jobs: job.schedule_removal()

                message_id_of_poll = poll_data.get("message_id")
                if message_id_of_poll:
                    # Останавливаем опрос только при принудительной остановке (was_stopped)
                    if was_stopped:
                        try:
                            await context.bot.stop_poll(chat_id=chat_id, message_id=message_id_of_poll)
                            logger.info(f"Активный опрос {poll_id_to_stop} (msg_id: {message_id_of_poll}) остановлен из-за принудительной остановки викторины.")
                        except BadRequest as e_stop_poll:
                            if "poll has already been closed" not in str(e_stop_poll).lower():
                                logger.warning(f"Не удалось остановить опрос {poll_id_to_stop} при финализации (was_stopped): {e_stop_poll}")
                        except Exception as e_gen_stop_poll:
                            logger.error(f"Общая ошибка при остановке опроса {poll_id_to_stop} (was_stopped): {e_gen_stop_poll}")
                    
                    # ИСПРАВЛЕНИЕ: Проверяем, есть ли placeholder сообщение "💡", которое нужно удалить
                    # Если solution еще не был отправлен (job был отменен), placeholder все равно нужно удалить
                    solution_placeholder_id = poll_data.get("solution_placeholder_message_id")
                    solution_msg_id_for_deletion = None

                    # Если есть placeholder, но solution еще не отправлен, используем placeholder ID для удаления
                    if solution_placeholder_id:
                        solution_msg_id_for_deletion = solution_placeholder_id
                        logger.debug(f"Placeholder сообщение {solution_placeholder_id} для poll {poll_id_to_stop} будет удалено (solution не был отправлен)")

                    # Добавляем прерванный опрос в список на батч-удаление (was_stopped or error_occurred)
                    # Это важно: при ошибке (например, таймаут) уже отправленные опросы нужно удалить
                    quiz_state.poll_and_solution_message_ids.append({
                        "poll_msg_id": message_id_of_poll,
                        "solution_msg_id": solution_msg_id_for_deletion
                    })
                    logger.debug(f"Poll msg {message_id_of_poll} (poll_id: {poll_id_to_stop}) добавлен в список на отложенное удаление (was_stopped={was_stopped}, error_occurred={error_occurred}, solution_msg_id={solution_msg_id_for_deletion}).")

                self.state.remove_current_poll(poll_id_to_stop)
            quiz_state.active_poll_ids_in_session.discard(poll_id_to_stop)

        if error_occurred and not quiz_state.scores:
            # Формируем понятное сообщение об ошибке для пользователя
            user_friendly_error = None
            if error_message:
                error_lower = error_message.lower()
                if "timed out" in error_lower or "timeout" in error_lower:
                    user_friendly_error = "Произошла задержка при отправке вопроса. Попробуйте начать викторину заново."
                elif "blocked" in error_lower or "not found" in error_lower or "forbidden" in error_lower:
                    user_friendly_error = "Бот не может отправить сообщение в этот чат. Проверьте настройки чата."
                elif "quizengine.send_quiz_poll вернул none" in error_lower:
                    user_friendly_error = "Произошла техническая ошибка при отправке вопроса. Попробуйте позже."
                else:
                    user_friendly_error = "Произошла ошибка при отправке вопроса. Попробуйте начать викторину заново."
            else:
                user_friendly_error = "Произошла непредвиденная ошибка. Попробуйте начать викторину заново."
            
            msg_text_to_send = f"⚠️ Викторина прервана\\.\n\n{escape_markdown_v2(user_friendly_error)}"
            try: 
                error_msg = await safe_send_message(
            bot=context.bot,
            chat_id=chat_id,
            text=msg_text_to_send,
            parse_mode=ParseMode.MARKDOWN_V2
        )
                # Добавляем сообщение об ошибке в глобальный список для периодической очистки
                self.state.add_message_for_deletion(chat_id, error_msg.message_id)
            except Exception as e_send_err: logger.error(f"Не удалось отправить сообщение об ошибке финализации: {e_send_err}")
        elif quiz_state.quiz_type != "single" or quiz_state.scores or (error_occurred and quiz_state.scores): 
            title_unescaped_for_formatter = "🏁 Викторина завершена!"
            if was_stopped: title_unescaped_for_formatter = "📝 Викторина остановлена. Результаты:"
            elif error_occurred: title_unescaped_for_formatter = f"⚠️ Викторина завершена с ошибкой{(': ' + error_message) if error_message else ''}. Результаты (если есть):"

            # Собираем данные результатов сессии, включая глобальный счет и иконку ачивки
            scores_for_display: List[Dict[str, Any]] = []
            try:
                profiles = await self.score_manager.get_session_profiles(chat_id, quiz_state.scores.keys())
                statistics_available = True
            except Exception:
                logger.exception("Статистика БД недоступна, показываем только результаты сессии")
                profiles = {}
                statistics_available = False
            for uid, data in quiz_state.scores.items():
                # Глобальная статистика пользователя (по всем чатам)
                global_stats = profiles.get(str(uid), {}).get("global")
                global_total_score_val = global_stats.get('total_score', 0) if global_stats else 0
                global_answered_polls_val = global_stats.get('answered_polls', 0) if global_stats else 0
                achievement_icon_val = self.score_manager.get_rating_icon(global_total_score_val)

                # Статистика пользователя в текущем чате
                current_chat_stats = profiles.get(str(uid), {}).get("chat")
                current_chat_score_val = current_chat_stats.get('total_score', 0) if current_chat_stats else 0
                current_chat_answered_val = current_chat_stats.get('answered_polls', 0) if current_chat_stats else 0
                current_chat_correct_val = current_chat_stats.get('correct_answers_count', 0) if current_chat_stats else 0

                try:
                    user_id_int = int(uid)
                except ValueError:
                    user_id_int = 0

                scores_for_display.append({
                    "statistics_available": statistics_available,
                    "user_id": user_id_int,
                    "name": data["name"],
                    "score": data["score"],
                    "correct_count": data.get("correct_count", 0),
                    "global_total_score": global_total_score_val,
                    "global_answered_polls": global_answered_polls_val,
                    "achievement_icon": achievement_icon_val,
                    "current_chat_score": current_chat_score_val,
                    "current_chat_answered": current_chat_answered_val,
                    "current_chat_correct": current_chat_correct_val,
                })

            scores_for_display.sort(key=lambda x: -x["score"])
            logger.info(f"Подготовлено {len(scores_for_display)} результатов для отображения в чате {chat_id}")

            results_text_md = self.score_manager.format_scores(
                scores_list=scores_for_display,
                title=title_unescaped_for_formatter,
                is_session_score=True,
                num_questions_in_session=quiz_state.num_questions_to_ask
            )

            # Проверяем, что текст результатов не пустой
            if not results_text_md or len(results_text_md.strip()) == 0:
                logger.error(f"Текст результатов викторины пустой для чата {chat_id}")
                results_text_md = f"🏁 Викторина завершена!\n\nУчастники: {len(scores_for_display)}\nОбщее количество вопросов: {quiz_state.num_questions_to_ask}"

            try:
                logger.info(f"Отправка результатов викторины в чат {chat_id}, длина текста: {len(results_text_md)}")
                result_msg = await safe_send_message(
            bot=context.bot,
            chat_id=chat_id,
            text=results_text_md,
            parse_mode=ParseMode.MARKDOWN_V2
        )
                logger.info(f"Результаты викторины успешно отправлены в чат {chat_id}, message_id: {result_msg.message_id}")
                # Добавляем результаты викторины в список для удаления через 2 минуты вместе с опросами
                quiz_state.results_message_ids.add(result_msg.message_id)
            except Exception as e_send_res:
                logger.error(f"Не удалось отправить результаты викторины в чат {chat_id}: {e_send_res}")
                logger.error(f"Текст результатов (первые 500 символов): {results_text_md[:500]}")
                # Попробуем отправить без Markdown форматирования в случае ошибки
                try:
                    if not is_formatting_error(e_send_res):
                        raise e_send_res  # Timeout/partial delivery must not create duplicate results.
                    fallback_text = f"🏁 Викторина завершена!\n\n{title_unescaped_for_formatter}\n\n"
                    for entry in scores_for_display[:10]:  # Показываем топ-10
                        name = entry.get('name', 'Unknown')
                        score = entry.get('score', 0)
                        correct = entry.get('correct_count', 0)
                        fallback_text += f"• {name}: {score} очков ({correct} правильных)\n"
                    fallback_msg = await safe_send_message(context.bot, chat_id, fallback_text, parse_mode=None)
                    logger.info(f"Отправлены результаты викторины без форматирования в чат {chat_id}")
                    # Добавляем fallback результаты в список для удаления через 2 минуты вместе с опросами
                    quiz_state.results_message_ids.add(fallback_msg.message_id)
                except Exception as e_fallback:
                    logger.error(f"Не удалось отправить даже fallback-сообщение: {e_fallback}")

        if self._pg_sessions:
            await self._queue_classic_messages(chat_id, quiz_state.results_message_ids)

        # PostgreSQL cleanup is performed by the durable worker, including streak messages.
        if quiz_state.message_ids_to_delete and not self._pg_sessions:
            logger.info(f"Немедленно удаляем {len(quiz_state.message_ids_to_delete)} сообщений о streak ачивках в чате {chat_id}")
            
            # Проверяем настройку автоудаления
            chat_settings = await self.data_manager.get_chat_settings_async(chat_id)
            default_auto_delete_from_config = self.app_config.default_chat_settings.get("auto_delete_bot_messages", True)
            auto_delete_enabled = chat_settings.get("auto_delete_bot_messages", default_auto_delete_from_config)
            
            if auto_delete_enabled:
                # Немедленно удаляем только streak ачивки (чатовые ачивки остаются навсегда)
                for msg_id in quiz_state.message_ids_to_delete:
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                        logger.info(f"Сообщение о streak ачивке {msg_id} немедленно удалено из чата {chat_id}")
                    except BadRequest as e_br_del:
                        if "message to delete not found" in str(e_br_del).lower() or \
                           "message can't be deleted" in str(e_br_del).lower():
                            logger.debug(f"Сообщение о streak ачивке {msg_id} уже удалено или не может быть удалено: {e_br_del}")
                        else:
                            logger.warning(f"Ошибка BadRequest при немедленном удалении сообщения о streak ачивке {msg_id}: {e_br_del}")
                    except Exception as e_del_immediate:
                        logger.warning(f"Не удалось немедленно удалить сообщение о streak ачивке {msg_id}: {e_del_immediate}")
                
                logger.info(f"Все {len(quiz_state.message_ids_to_delete)} сообщений о streak ачивках немедленно удалены из чата {chat_id}")
            else:
                logger.info(f"Автоудаление отключено для чата {chat_id}. Streak ачивки не удалены.")
        else:
            logger.debug(f"Нет сообщений о streak ачивках для удаления в чате {chat_id}.")

        # БАТЧ УДАЛЕНИЕ: Удаляем все сообщения викторины (опросы + пояснения + результаты) одной задачей
        if quiz_state.poll_and_solution_message_ids or quiz_state.results_message_ids:
            all_messages_to_delete_flat: List[int] = []

            # Добавляем опросы и пояснения
            for pair in quiz_state.poll_and_solution_message_ids:
                if pair.get("poll_msg_id"):
                    all_messages_to_delete_flat.append(pair["poll_msg_id"])
                if pair.get("solution_msg_id"):
                    all_messages_to_delete_flat.append(pair["solution_msg_id"])

            # Добавляем результаты викторины
            for result_msg_id in quiz_state.results_message_ids:
                all_messages_to_delete_flat.append(result_msg_id)

            if all_messages_to_delete_flat and self._pg_sessions:
                await self._queue_classic_messages(chat_id, all_messages_to_delete_flat)
            elif all_messages_to_delete_flat:
                # ФАЛЛБЭК: Сначала добавляем ВСЕ сообщения в fallback (защита от сбоя delayed задачи)
                for msg_id in all_messages_to_delete_flat:
                    self.state.add_message_for_deletion(chat_id, msg_id, delay_seconds=0)
                logger.info(f"🛡️ Добавлено {len(all_messages_to_delete_flat)} сообщений викторины в fallback защиту (чат {chat_id})")

                # Планируем одну батч-задачу на удаление всех сообщений
                job_name_cleanup = f"delayed_quiz_cleanup_chat_{chat_id}_qs_{int(quiz_state.quiz_start_time.timestamp())}"
                schedule_job_unique(
                    job_queue,
                    job_name=job_name_cleanup,
                    callback=self._delayed_delete_poll_solution_messages_job,
                    when=timedelta(seconds=DELAY_BEFORE_POLL_SOLUTION_DELETION_SECONDS),
                    data={"chat_id": chat_id, "message_ids": all_messages_to_delete_flat}
                )
                logger.info(f"📅 Запланировано батч-удаление {len(all_messages_to_delete_flat)} сообщений викторины через {DELAY_BEFORE_POLL_SOLUTION_DELETION_SECONDS}s (job: {job_name_cleanup})")
        else:
            logger.debug(f"Нет сообщений викторины для отложенного удаления в чате {chat_id}.")

        # ОБНОВЛЯЕМ СТАТИСТИКУ КАТЕГОРИЙ ПОСЛЕ ЗАВЕРШЕНИЯ ВИКТОРИНЫ
        # (только если викторина завершилась успешно, один раз за сессию)
        if not self._pg_sessions and not error_occurred and hasattr(self.data_manager, 'category_manager') and self.data_manager.category_manager:
            # Собираем все уникальные категории, использованные в этой викторине
            used_categories_in_session = set()
            for question_data in quiz_state.questions:
                category_name = question_data.get('current_category_name_for_quiz') or question_data.get('original_category')
                if category_name:
                    used_categories_in_session.add(category_name)

            if used_categories_in_session:
                logger.info(f"Обновление статистики категорий после завершения викторины в чате {chat_id}. Категории: {', '.join(used_categories_in_session)}")

                # Обновляем статистику для каждой использованной категории (+1 за викторину)
                for category in used_categories_in_session:
                    try:
                        self.data_manager.category_manager._update_category_usage_sync(category, chat_id)
                        logger.debug(f"✅ Статистика категории '{category}' обновлена (+1) в чате {chat_id}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка при обновлении статистики категории '{category}' в чате {chat_id}: {e}")

                logger.info(f"✅ Статистика {len(used_categories_in_session)} категорий обновлена после завершения викторины в чате {chat_id}")
            else:
                logger.debug(f"ℹ️ В викторине чата {chat_id} не найдены категории для обновления статистики")

        # Сохраняем состояние викторин после финализации (на случай перезапуска)
        try:
            if hasattr(self.data_manager, 'save_active_quizzes'):
                self.data_manager.save_active_quizzes()
                logger.debug(f"Состояние викторин сохранено после финализации чата {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка сохранения состояния викторин после финализации чата {chat_id}: {e}")

        logger.info(f"Викторина в чате {chat_id} полностью финализирована (основная часть). Отложенные задачи могут выполняться.")

    async def quiz_command_entry(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        logger.debug(f"quiz_command_entry: ПОЛУЧЕНА КОМАНДА /quiz. Update ID: {update.update_id}")
        if not update.message or not update.effective_chat or not update.effective_user:
            logger.debug("quiz_command_entry: update.message, effective_chat или effective_user отсутствуют.")
            return ConversationHandler.END

        chat_id = update.effective_chat.id
        user = update.effective_user
        logger.info(f"Команда /quiz ({self.app_config.commands.quiz}) вызвана пользователем {user.id} ({user.full_name}) в чате {chat_id}. Аргументы: {context.args}")

        # Обновляем метаданные чата (название, тип) в фоновом режиме
        asyncio.create_task(self.data_manager.update_chat_metadata(chat_id, context.bot))

        active_quiz = self.state.get_active_quiz(chat_id)
        if active_quiz and not active_quiz.is_stopping:
            logger.info(f"quiz_command_entry: Викторина уже активна в чате {chat_id}. Отправка сообщения.")
            await update.message.reply_text(escape_markdown_v2(f"Викторина уже идет. Остановите ее: `/{self.app_config.commands.stop_quiz}`."), parse_mode=ParseMode.MARKDOWN_V2)
            return ConversationHandler.END

        args = context.args if context.args else []
        parsed_num_q: Optional[int] = None
        parsed_categories_names: List[str] = []
        parsed_announce_flag: Optional[bool] = None
        temp_args_for_parsing = list(args)

        if temp_args_for_parsing and temp_args_for_parsing[-1].lower() == "announce":
            parsed_announce_flag = True
            temp_args_for_parsing.pop()
            logger.debug("quiz_command_entry: Аргумент 'announce' обнаружен.")

        if temp_args_for_parsing and temp_args_for_parsing[0].isdigit():
            try:
                num_val = int(temp_args_for_parsing[0])
                if 1 <= num_val <= self.app_config.max_questions_per_session:
                    parsed_num_q = num_val
                    temp_args_for_parsing.pop(0)
                    logger.debug(f"quiz_command_entry: Количество вопросов из аргументов: {parsed_num_q}")
                else:
                    logger.info(f"quiz_command_entry: Некорректное количество вопросов в аргументах: {num_val}. Чат: {chat_id}")
                    await update.message.reply_text(f"Количество вопросов должно быть от 1 до {escape_markdown_v2(str(self.app_config.max_questions_per_session))}\\.", parse_mode=ParseMode.MARKDOWN_V2)
                    return ConversationHandler.END
            except ValueError:
                logger.debug(f"quiz_command_entry: Первый аргумент '{temp_args_for_parsing[0]}' не является числом (если остался после announce).")

        if temp_args_for_parsing:
            potential_category_name = " ".join(temp_args_for_parsing)
            if self.category_manager.is_valid_category(potential_category_name):
                parsed_categories_names.append(potential_category_name)
                logger.debug(f"quiz_command_entry: Категория из аргументов: '{potential_category_name}'")
            else:
                logger.debug(f"quiz_command_entry: Строка '{potential_category_name}' из аргументов не является валидной категорией.")

        is_quick_launch = parsed_num_q is not None or bool(parsed_categories_names)
        logger.debug(f"quiz_command_entry: Быстрый запуск: {is_quick_launch}. NQ: {parsed_num_q}, Cats: {parsed_categories_names}, AnnounceFlag: {parsed_announce_flag}")

        if is_quick_launch:
            logger.info(f"quiz_command_entry: Быстрый запуск викторины для чата {chat_id}.")
            params_for_quick_launch = await self._get_effective_quiz_params(chat_id, parsed_num_q)
            final_announce_for_quick = parsed_announce_flag if parsed_announce_flag is not None else params_for_quick_launch["announce_quiz"]
            final_is_random_cats_for_quick = not bool(parsed_categories_names)
            await self._initiate_quiz_session(
                context, chat_id, user,
                params_for_quick_launch["quiz_type_key"], params_for_quick_launch["quiz_mode"],
                params_for_quick_launch["num_questions"], params_for_quick_launch["open_period_seconds"],
                final_announce_for_quick, params_for_quick_launch["announce_delay_seconds"],
                category_names_for_quiz=parsed_categories_names if parsed_categories_names else None,
                is_random_categories_mode=final_is_random_cats_for_quick,
                interval_seconds=params_for_quick_launch.get("interval_seconds") if "interval_seconds" in params_for_quick_launch else None,
                original_command_message_id=update.message.message_id,
                interactive_start_message_id=None
            )
            return ConversationHandler.END
        elif parsed_announce_flag is True:
            logger.info(f"quiz_command_entry: Быстрый запуск викторины (только флаг announce) для чата {chat_id}.")
            params_for_announce_only = await self._get_effective_quiz_params(chat_id)
            await self._initiate_quiz_session(
                context, chat_id, user,
                params_for_announce_only["quiz_type_key"], params_for_announce_only["quiz_mode"],
                params_for_announce_only["num_questions"], params_for_announce_only["open_period_seconds"],
                True, params_for_announce_only["announce_delay_seconds"],
                is_random_categories_mode=True,
                interval_seconds=params_for_announce_only.get("interval_seconds") if "interval_seconds" in params_for_announce_only else None,
                original_command_message_id=update.message.message_id,
                interactive_start_message_id=None
            )
            return ConversationHandler.END
        else:
            logger.info(f"quiz_command_entry: Переход к интерактивной настройке викторины для чата {chat_id}.")
            params_for_interactive = await self._get_effective_quiz_params(chat_id)
            
            # Загружаем сохраненные настройки из базы данных
            saved_num_questions = self.data_manager.get_quiz_setting(chat_id, "num_questions", params_for_interactive["num_questions"])
            saved_announce = self.data_manager.get_quiz_setting(chat_id, "announce", params_for_interactive["announce_quiz"])
            saved_open_period = self.data_manager.get_quiz_setting(chat_id, "open_period_seconds", params_for_interactive["open_period_seconds"])
            saved_interval = self.data_manager.get_quiz_setting(chat_id, "interval_seconds", params_for_interactive.get("interval_seconds"))
            
            # Загружаем настройки категорий
            saved_categories_mode = self.data_manager.get_quiz_setting(chat_id, "categories_mode", "random")
            saved_num_random_categories = self.data_manager.get_quiz_setting(chat_id, "num_random_categories", 3)
            saved_specific_categories = self.data_manager.get_quiz_setting(chat_id, "specific_categories", [])
            
            context.chat_data['quiz_cfg_progress'] = {
                'num_questions': saved_num_questions,
                'announce': saved_announce, 
                'open_period_seconds': saved_open_period,
                'announce_delay_seconds': params_for_interactive["announce_delay_seconds"], 
                'quiz_type_key': params_for_interactive["quiz_type_key"],
                'quiz_mode': params_for_interactive["quiz_mode"], 
                'interval_seconds': saved_interval,
                'categories_mode': saved_categories_mode,
                'num_random_categories': saved_num_random_categories,
                'specific_categories': saved_specific_categories,
                'original_command_message_id': update.message.message_id, 
                'chat_id': chat_id, 
                'user_id': user.id
            }
            
            logger.info(f"Загружены настройки для чата {chat_id}: вопросы={saved_num_questions}, анонс={saved_announce}, время={saved_open_period}, интервал={saved_interval}, режим_категорий={saved_categories_mode}, случайных_категорий={saved_num_random_categories}, выбранных_категорий={len(saved_specific_categories)}")
            logger.debug(f"quiz_command_entry: Вызываем _send_quiz_cfg_message для чата {chat_id}")
            try:
                await self._send_quiz_cfg_message(update, context)
                logger.debug(f"quiz_command_entry: _send_quiz_cfg_message успешно выполнен для чата {chat_id}")
            except Exception as e:
                logger.error(f"quiz_command_entry: Ошибка в _send_quiz_cfg_message для чата {chat_id}: {e}", exc_info=True)
                await update.message.reply_text("Произошла ошибка при настройке викторины. Пожалуйста, попробуйте еще раз.")
            return CFG_QUIZ_OPTIONS

    async def _send_quiz_cfg_message(self, update_or_query: Union[Update, CallbackQuery], context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.debug(f"_send_quiz_cfg_message: Начало выполнения. Тип: {type(update_or_query).__name__}")
        cfg = context.chat_data.get('quiz_cfg_progress')
        logger.debug(f"_send_quiz_cfg_message: Данные конфигурации: {cfg}")
        if not cfg:
            logger.error("_send_quiz_cfg_message: Данные 'quiz_cfg_progress' не найдены.")
            if isinstance(update_or_query, CallbackQuery):
                await update_or_query.answer("Ошибка конфигурации. Пожалуйста, начните заново.", show_alert=True)
                if update_or_query.message:
                    try: await update_or_query.message.delete()
                    except Exception: pass
            return

        # СИНХРОНИЗИРУЕМ: Обновляем cfg из базы данных для актуальности
        chat_id = cfg.get('chat_id')
        if chat_id:
            cfg['num_questions'] = self.data_manager.get_quiz_setting(chat_id, "num_questions", cfg['num_questions'])
            cfg['announce'] = self.data_manager.get_quiz_setting(chat_id, "announce", cfg['announce'])
            cfg['open_period_seconds'] = self.data_manager.get_quiz_setting(chat_id, "open_period_seconds", cfg['open_period_seconds'])
            cfg['interval_seconds'] = self.data_manager.get_quiz_setting(chat_id, "interval_seconds", cfg['interval_seconds'])
            cfg['categories_mode'] = self.data_manager.get_quiz_setting(chat_id, "categories_mode", cfg['categories_mode'])
            cfg['num_random_categories'] = self.data_manager.get_quiz_setting(chat_id, "num_random_categories", cfg['num_random_categories'])
            cfg['specific_categories'] = self.data_manager.get_quiz_setting(chat_id, "specific_categories", cfg['specific_categories'])

        num_q_display = cfg['num_questions']
        
        # Используем настройки категорий из cfg (уже загружены)
        current_mode = cfg.get('categories_mode', 'random')
        current_pool = cfg.get('specific_categories', [])
        num_random = cfg.get('num_random_categories', 3)
        
        # Формируем отображаемый текст для категорий
        if current_mode == 'random':
            cat_display_text_escaped = escape_markdown_v2(f'🎲 Случайные ({num_random})')
        elif current_mode == 'specific':
            if current_pool:
                cat_display_text_escaped = escape_markdown_v2(f'🗂️ Выбранные ({len(current_pool)})')
            else:
                cat_display_text_escaped = escape_markdown_v2('🗂️ Выбранные (пусто)')
        else:
            cat_display_text_escaped = escape_markdown_v2('🎲 Случайные')
            
        announce_text_raw_escaped = escape_markdown_v2('Вкл' if cfg['announce'] else 'Выкл')
        
        # Получаем эффективный интервал из настроек пользователя
        effective_interval = cfg.get('interval_seconds')
        
        # Определяем, включен ли интервал
        interval_enabled = 'interval_seconds' in cfg and cfg.get('interval_seconds') is not None
        interval_text = escape_markdown_v2(f" ({effective_interval} сек)") if interval_enabled and effective_interval else ""
        
        # Получаем эффективное время ответа
        effective_open_period = cfg.get('open_period_seconds')
        if effective_open_period is None:
            effective_params = await self._get_effective_quiz_params(cfg['chat_id'], cfg['num_questions'])
            effective_open_period = effective_params.get('open_period_seconds', 30)
        
        text = (
            f"⚙️ *{escape_markdown_v2('Настройка викторины')}*\n\n"
            f"🔢 {escape_markdown_v2('Количество вопросов:')} `{escape_markdown_v2(str(num_q_display))}`\n"
            f"📚 {escape_markdown_v2('Категория:')} `{cat_display_text_escaped}`\n"
            f"⏰ {escape_markdown_v2('Время ответа:')} `{escape_markdown_v2(str(effective_open_period))} сек`\n"
            f"📢 {escape_markdown_v2('Анонс:')} `{announce_text_raw_escaped}`\n"
            f"⏱️ {escape_markdown_v2('Интервал:')} `{escape_markdown_v2('Вкл' if interval_enabled else 'Выкл')}`{interval_text}\n\n"
            f"{escape_markdown_v2('Выберите параметр или запустите.')}"
        )
        
        # Формируем текст кнопки для категорий (используем настройки из cfg)
        if current_mode == 'random':
            cat_button_text_plain = f'🎲 Случайные {num_random}'
        elif current_mode == 'specific':
            if current_pool:
                cat_button_text_plain = f'🗂️ Выбранные {len(current_pool)}'
            else:
                cat_button_text_plain = '🗂️ Выбранные'
        else:
            cat_button_text_plain = '🎲 Случайные'
            
        if len(cat_button_text_plain) > 18 : cat_button_text_plain = cat_button_text_plain[:15] + "..."
        announce_button_text_plain = 'Вкл' if cfg['announce'] else 'Выкл'
        interval_button_text_plain = 'Вкл' if interval_enabled else 'Выкл'
        open_period_button_text_plain = f"{effective_open_period} сек"
        kb_layout = [
            [InlineKeyboardButton(f"🔢 Вопросы: {num_q_display}", callback_data=CB_QCFG_NUM_MENU), InlineKeyboardButton(f"📚 Категория: {cat_button_text_plain}", callback_data=CB_QCFG_CAT_MENU)],
            [InlineKeyboardButton(f"⏰ Время ответа: {open_period_button_text_plain}", callback_data=CB_QCFG_OPEN_PERIOD), InlineKeyboardButton(f"⏱️ Интервал: {interval_button_text_plain}", callback_data=CB_QCFG_INTERVAL)],
            [InlineKeyboardButton(f"📢 Анонс: {announce_button_text_plain}", callback_data=CB_QCFG_ANNOUNCE)],
            [InlineKeyboardButton("▶️ Начать игру", callback_data=CB_QCFG_START, style='success')],
            [InlineKeyboardButton("‹ Главное меню", callback_data='nav:home'), InlineKeyboardButton("Отмена", callback_data=CB_QCFG_CANCEL)]
        ]
        markup = InlineKeyboardMarkup(kb_layout)
        from modules.telegram_menu import card, acknowledge
        target = context.chat_data.get('_menu_entry_message_id') or context.chat_data.get('_quiz_cfg_msg_id')
        sent = await card(update_or_query, context, text, markup.inline_keyboard,
                          parse_mode=ParseMode.MARKDOWN_V2, message_id=target)
        if sent:
            context.chat_data['_quiz_cfg_msg_id'] = sent.message_id
        elif target:
            context.chat_data['_quiz_cfg_msg_id'] = target
        if isinstance(update_or_query, CallbackQuery):
            await acknowledge(update_or_query)

    async def handle_quiz_cfg_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        query = update.callback_query
        if not query or not query.data:
            if query: await query.answer("Ошибка: нет данных в колбэке.", show_alert=True)
            return CFG_QUIZ_OPTIONS

        action = query.data
        user_id = query.from_user.id if query.from_user else "Unknown"
        chat_id = query.message.chat.id if query.message else "Unknown"
        
        # Логируем все нажатия кнопок на уровне DEBUG
        logger.debug(f"🔘 Нажата кнопка: {action} | Пользователь: {user_id} | Чат: {chat_id}")
        
        cfg = context.chat_data.get('quiz_cfg_progress')
        if not cfg:
            await query.answer("Сессия настройки истекла или повреждена. Пожалуйста, начните заново.", show_alert=True)
            if query.message:
                try: await query.message.delete()
                except Exception: pass
            return ConversationHandler.END
        if query.from_user.id != cfg.get('user_id'):
            await query.answer("Вы не можете изменять настройки этой викторины.", show_alert=True)
            return CFG_QUIZ_OPTIONS

        if action == CB_QCFG_START:
            logger.info(f"Запуск викторины из интерактивной настройки для чата {cfg.get('chat_id')}. Пользователь: {query.from_user.id}")
            
            # ПРОВЕРЯЕМ: Все настройки на корректность согласно документации
            chat_id = cfg.get('chat_id')
            if not chat_id:
                await query.answer("Ошибка: не удалось определить чат. Проверьте настройки.", show_alert=True)
                return CFG_QUIZ_OPTIONS
            
            # Проверяем количество вопросов
            num_questions = cfg.get('num_questions', 0)
            if not (1 <= num_questions <= self.app_config.max_questions_per_session):
                await query.answer(f"Ошибка: некорректное количество вопросов ({num_questions}). Допустимо от 1 до {self.app_config.max_questions_per_session}. Проверьте настройки.", show_alert=True)
                return CFG_QUIZ_OPTIONS
            
            # Проверяем время ответа
            open_period = cfg.get('open_period_seconds')
            if open_period is not None and not (10 <= open_period <= 300):
                await query.answer(f"Ошибка: некорректное время ответа ({open_period} сек). Допустимо от 10 до 300 секунд. Проверьте настройки.", show_alert=True)
                return CFG_QUIZ_OPTIONS
            
            # Проверяем интервал
            interval = cfg.get('interval_seconds')
            if interval is not None and not (5 <= interval <= 300):
                await query.answer(f"Ошибка: некорректный интервал ({interval} сек). Допустимо от 5 до 300 секунд. Проверьте настройки.", show_alert=True)
                return CFG_QUIZ_OPTIONS
            
            # Проверяем режим категорий
            categories_mode = cfg.get('categories_mode', 'random')
            if categories_mode == 'specific':
                specific_categories = cfg.get('specific_categories', [])
                if not specific_categories:
                    await query.answer("Ошибка: выбран режим 'выбранные категории', но категории не выбраны. Проверьте настройки.", show_alert=True)
                    return CFG_QUIZ_OPTIONS
            elif categories_mode == 'random':
                num_random = cfg.get('num_random_categories', 0)
                if not (1 <= num_random <= 10):
                    await query.answer(f"Ошибка: некорректное количество случайных категорий ({num_random}). Допустимо от 1 до 10. Проверьте настройки.", show_alert=True)
                    return CFG_QUIZ_OPTIONS
            
            # Если все проверки пройдены, продолжаем запуск
            final_cfg = context.chat_data.pop('quiz_cfg_progress')
            quiz_cfg_msg_id = context.chat_data.pop('_quiz_cfg_msg_id', None)
            context.chat_data.pop('_quiz_cmd_msg_id', None)

            # Простое сообщение о запуске
            start_message_text_escaped = escape_markdown_v2("🚀 Запускаю викторину...")
            interactive_start_message_id_to_pass: Optional[int] = None

            if quiz_cfg_msg_id and final_cfg.get('chat_id'):
                deletion_success = False
                try:
                    if quiz_cfg_msg_id != final_cfg.get('original_command_message_id'):
                        await context.bot.delete_message(chat_id=final_cfg['chat_id'], message_id=quiz_cfg_msg_id)
                        deletion_success = True
                        logger.debug(f"✅ Сообщение настройки {quiz_cfg_msg_id} удалено сразу")
                except Exception as e_del_menu:
                    logger.warning(f"❌ Не удалось сразу удалить сообщение меню конфигурации {quiz_cfg_msg_id}: {e_del_menu}")

                # ФАЛБЭК: Если не удалось удалить сразу, добавляем в систему автоудаления
                if not deletion_success and quiz_cfg_msg_id != final_cfg.get('original_command_message_id'):
                    self.state.add_message_for_deletion(final_cfg['chat_id'], quiz_cfg_msg_id, delay_seconds=10)
                    logger.info(f"📋 Сообщение настройки {quiz_cfg_msg_id} добавлено в автоудаление (fallback через 10 сек)")

            if final_cfg.get('chat_id'):
                try:
                    sent_launch_msg = await safe_send_message(
                        bot=context.bot,
                        chat_id=final_cfg['chat_id'],
                        text=start_message_text_escaped,
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    interactive_start_message_id_to_pass = sent_launch_msg.message_id
                    # Добавляем сообщение "Запускаю викторину..." в автоудаление (30 сек)
                    if sent_launch_msg:
                        self.state.add_message_for_deletion(final_cfg['chat_id'], sent_launch_msg.message_id, delay_seconds=30)
                except Exception as e_send_launch:
                    logger.error(f"Не удалось отправить сообщение 'Запускаю викторину...': {e_send_launch}")

            await query.answer()

            # Получаем эффективный интервал из настроек пользователя
            effective_interval = final_cfg.get('interval_seconds')
            
            # Получаем настройки категорий из чата
            chat_settings = await self.data_manager.get_chat_settings_async(final_cfg['chat_id'])
            categories_mode = self.data_manager.get_quiz_setting(final_cfg['chat_id'], "categories_mode", 'random')
            categories_pool = self.data_manager.get_quiz_setting(final_cfg['chat_id'], "specific_categories", [])
            
            if categories_mode == 'specific' and categories_pool:
                # Используем выбранные категории
                category_names_for_quiz = categories_pool
                is_random_categories_mode = False
                logger.info(f"Запуск викторины с выбранными категориями: {categories_pool}")
            else:
                # Используем случайные категории
                category_names_for_quiz = None
                is_random_categories_mode = True
                num_random_categories = self.data_manager.get_quiz_setting(final_cfg['chat_id'], "num_random_categories", 3)
                logger.info(f"Запуск викторины со случайными категориями: {num_random_categories} категорий")
            
            await self._initiate_quiz_session(
                context, final_cfg['chat_id'], query.from_user, final_cfg['quiz_type_key'], final_cfg['quiz_mode'],
                final_cfg['num_questions'], final_cfg['open_period_seconds'], final_cfg['announce'], final_cfg['announce_delay_seconds'],
                category_names_for_quiz=category_names_for_quiz,
                is_random_categories_mode=is_random_categories_mode,
                interval_seconds=effective_interval,
                original_command_message_id=final_cfg.get('original_command_message_id'),
                interactive_start_message_id=interactive_start_message_id_to_pass
            )
            return ConversationHandler.END
        
        if action == CB_QCFG_BACK:
            logger.debug(f"Обработка кнопки 'Назад' в состоянии {context.chat_data.get('_current_state', 'неизвестно')}")
            
            # Кнопка "Назад" - НЕ применяем настройки, просто возвращаемся к предыдущему меню
            # Очищаем временные настройки
            context.chat_data.pop('_temp_quiz_categories_mode', None)
            context.chat_data.pop('_editing_interval', None)
            context.chat_data.pop('_editing_open_period', None)
            context.chat_data.pop('_editing_random_categories', None)
            context.chat_data.pop('_temp_categories_pool', None)
            context.chat_data.pop('_quiz_category_id_map', None)
            
            await self._send_quiz_cfg_message(query, context) 
            return CFG_QUIZ_OPTIONS
        elif action == CB_QCFG_NUM_MENU:
            kb_num_options = [[InlineKeyboardButton("1", callback_data=f"{CB_QCFG_NUM_VAL}:1"), InlineKeyboardButton("5", callback_data=f"{CB_QCFG_NUM_VAL}:5"), InlineKeyboardButton("10", callback_data=f"{CB_QCFG_NUM_VAL}:10")],
                              [InlineKeyboardButton("Другое число...", callback_data=f"{CB_QCFG_NUM_VAL}:custom")], [InlineKeyboardButton("⬅️ Назад", callback_data=CB_QCFG_BACK)]]
            if query.message:
                await query.message.edit_text(escape_markdown_v2("Выберите количество вопросов:"), reply_markup=InlineKeyboardMarkup(kb_num_options), parse_mode=ParseMode.MARKDOWN_V2)
            await query.answer()
            return CFG_QUIZ_OPTIONS
        elif action.startswith(CB_QCFG_NUM_VAL):
            val_str = action.split(":", 1)[1]
            if val_str == "custom":
                custom_prompt_text = (f"Введите количество вопросов \\(от 1 до {escape_markdown_v2(str(self.app_config.max_questions_per_session))}\\)\\.\n"
                                      f"Или `/{escape_markdown_v2(self.app_config.commands.cancel)}` для отмены\\.")
                if query.message:
                    await query.message.edit_text(custom_prompt_text, reply_markup=None, parse_mode=ParseMode.MARKDOWN_V2)
                await query.answer()
                return CFG_QUIZ_NUM_QS
            else:
                try:
                    num = int(val_str)
                    if 1 <= num <= self.app_config.max_questions_per_session:
                        cfg['num_questions'] = num
                        # Сохраняем настройку в базу данных
                        if cfg.get('chat_id'):
                            await self.data_manager.update_quiz_setting(cfg['chat_id'], "num_questions", num)
                            logger.info(f"Сохранена настройка количества вопросов для чата {cfg['chat_id']}: {num}")
                        effective_params_after_num_change = await self._get_effective_quiz_params(cfg['chat_id'], num)
                        cfg['quiz_type_key'] = effective_params_after_num_change['quiz_type_key']
                        cfg['quiz_mode'] = effective_params_after_num_change['quiz_mode']
                    else: await query.answer(f"Некорректное число: {num}. Допустимо от 1 до {self.app_config.max_questions_per_session}.", show_alert=True)
                except ValueError: await query.answer(f"Ошибка значения числа: {val_str}.", show_alert=True)
                await self._send_quiz_cfg_message(query, context) 
                return CFG_QUIZ_OPTIONS
        elif action == CB_QCFG_CAT_MENU:
            # Показываем меню выбора категорий с режимами
            logger.info(f"Обработка CB_QCFG_CAT_MENU для чата {cfg.get('chat_id')}")
            chat_id = cfg.get('chat_id')
            
            # Показываем текущее состояние из базы данных
            settings = await self.data_manager.get_chat_settings_async(chat_id) if chat_id else {}
            current_mode = self.data_manager.get_quiz_setting(chat_id, "categories_mode", 'random')
            current_pool = self.data_manager.get_quiz_setting(chat_id, "specific_categories", [])
                
            mode_display = {
                'random': '🎲 Случайные',
                'specific': '🗂️ Выбранные'
            }.get(current_mode, '🎲 Случайные')
            
            # Формируем текст в зависимости от режима
            if current_mode == 'random':
                text = (
                    f"📚 *Выбор категорий*\n\n"
                    f"🎯 *Текущий режим:* {escape_markdown_v2(mode_display)}\n"
                    f"📝 *Количество случайных категорий:* {escape_markdown_v2(str(self.data_manager.get_quiz_setting(chat_id, 'num_random_categories', 3)))}\n\n"
                    f"{escape_markdown_v2('Выберите режим:')}"
                )
            else:
                pool_display = ', '.join(current_pool) if current_pool else 'не настроен'
                text = (
                    f"📚 *Выбор категорий*\n\n"
                    f"🎯 *Текущий режим:* {escape_markdown_v2(mode_display)}\n"
                    f"📝 *Пул категорий:* {escape_markdown_v2(pool_display)}\n\n"
                    f"{escape_markdown_v2('Выберите режим:')}"
                )
            
            # Кнопки режимов с переключателями
            cat_kb_list = [
                [InlineKeyboardButton(f"{'✅ ' if current_mode == 'random' else '☑️ '}🎲 Случайные", callback_data=f"{CB_QCFG_CAT_POOL_MODE}:random")],
                [InlineKeyboardButton(f"{'✅ ' if current_mode == 'specific' else '☑️ '}🗂️ Выбранные", callback_data=f"{CB_QCFG_CAT_POOL_MODE}:specific")]
            ]
            
            cat_kb_list.append([InlineKeyboardButton("⬅️ Назад", callback_data=CB_QCFG_BACK)])
            
            if query.message:
                await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(cat_kb_list), parse_mode=ParseMode.MARKDOWN_V2)
            await query.answer()
            return CFG_QUIZ_OPTIONS
        elif action.startswith(CB_QCFG_CAT_VAL):
            selected_category_name = action.split(":", 1)[1]
            cfg['category_name'] = selected_category_name
            await self._send_quiz_cfg_message(query, context) 
            return CFG_QUIZ_OPTIONS
        elif action == CB_QCFG_NOOP:
            await query.answer("Для выбора других категорий, пожалуйста, используйте команду /quiz с указанием имени категории.", show_alert=True)
            return CFG_QUIZ_OPTIONS
        elif action == CB_QCFG_ANNOUNCE:
            cfg['announce'] = not cfg['announce']
            # Сохраняем настройку в базу данных
            if cfg.get('chat_id'):
                await self.data_manager.update_quiz_setting(cfg['chat_id'], "announce", cfg['announce'])
                logger.info(f"Сохранена настройка анонса для чата {cfg['chat_id']}: {cfg['announce']}")
            await self._send_quiz_cfg_message(query, context) 
            return CFG_QUIZ_OPTIONS
        elif action == CB_QCFG_INTERVAL:
            logger.debug(f"Обработка настройки интервала для чата {cfg.get('chat_id')}")
            # Показываем меню для настройки интервала
            current_interval = cfg.get('interval_seconds')
            effective_params = await self._get_effective_quiz_params(cfg['chat_id'], cfg['num_questions'])
            default_interval = effective_params.get('interval_seconds', 30)
            
            if current_interval is not None:
                # Интервал включен - показываем опции выключения или изменения
                kb_interval_options = [
                    [InlineKeyboardButton("❌ Выключить интервал", callback_data=f"{CB_QCFG_INTERVAL_OPT}:off")],
                    [InlineKeyboardButton("⚙️ Изменить значение", callback_data=f"{CB_QCFG_INTERVAL_OPT}:custom")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data=CB_QCFG_BACK)]
                ]
                interval_menu_text = f"Интервал между вопросами: {current_interval} сек\n\nВыберите действие:"
            else:
                # Интервал выключен - показываем опции включения или настройки
                kb_interval_options = [
                    [InlineKeyboardButton("✅ Включить интервал", callback_data=f"{CB_QCFG_INTERVAL_OPT}:on")],
                    [InlineKeyboardButton("⚙️ Настроить вручную", callback_data=f"{CB_QCFG_INTERVAL_OPT}:custom")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data=CB_QCFG_BACK)]
                ]
                interval_menu_text = f"Интервал между вопросами: выключен\n\nВыберите действие:"
            
            await query.message.edit_text(
                escape_markdown_v2(interval_menu_text),
                reply_markup=InlineKeyboardMarkup(kb_interval_options),
                parse_mode=ParseMode.MARKDOWN_V2
            )
            await query.answer()
            return CFG_QUIZ_INTERVAL_OPTIONS
        elif action.startswith(CB_QCFG_INTERVAL_OPT):
            opt_type = action.split(":", 1)[1]
            if opt_type == "off":
                # Выключаем интервал
                cfg['interval_seconds'] = None
                # Сохраняем настройку в базу данных
                if cfg.get('chat_id'):
                    await self.data_manager.update_quiz_setting(cfg['chat_id'], "interval_seconds", None)
                    logger.info(f"Сохранена настройка интервала для чата {cfg['chat_id']}: выключен")
                await query.answer("Интервал выключен")
                await self._send_quiz_cfg_message(query, context)
                return CFG_QUIZ_OPTIONS
            elif opt_type == "on":
                # Включаем интервал с дефолтным значением из настроек чата
                effective_params = await self._get_effective_quiz_params(cfg['chat_id'], cfg['num_questions'])
                interval_value = effective_params.get('interval_seconds', 30)
                cfg['interval_seconds'] = interval_value
                # Сохраняем настройку в базу данных
                if cfg.get('chat_id'):
                    await self.data_manager.update_quiz_setting(cfg['chat_id'], "interval_seconds", interval_value)
                    logger.info(f"Сохранена настройка интервала для чата {cfg['chat_id']}: {interval_value} сек")
                await query.answer("Интервал включен с дефолтным значением")
                await self._send_quiz_cfg_message(query, context)
                return CFG_QUIZ_OPTIONS
            elif opt_type == "custom":
                # Показываем поле для ввода значения
                context.chat_data['_editing_interval'] = True
                interval_text = f"Введите интервал между вопросами в секундах \\(от 5 до 300\\):\n\nТекущее значение: {cfg.get('interval_seconds', 'выключен')}"
                await query.message.edit_text(
                    interval_text,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=CB_QCFG_BACK)]]),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                await query.answer()
                return CFG_QUIZ_INTERVAL_INPUT
        elif action == CB_QCFG_OPEN_PERIOD:
            # Показываем меню для настройки времени ответа
            current_open_period = cfg.get('open_period_seconds')
            effective_params = await self._get_effective_quiz_params(cfg['chat_id'], cfg['num_questions'])
            default_open_period = effective_params.get('open_period_seconds', 30)
            
            if current_open_period is not None:
                # Время ответа настроено - показываем опции изменения
                kb_open_period_options = [
                    [InlineKeyboardButton("⚙️ Изменить значение", callback_data=f"{CB_QCFG_OPEN_PERIOD_OPT}:custom")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data=CB_QCFG_BACK)]
                ]
                open_period_menu_text = f"Время на ответ: {current_open_period} сек\n\nВыберите действие:"
            else:
                # Время ответа не настроено - показываем опции настройки
                kb_open_period_options = [
                    [InlineKeyboardButton("✅ Использовать по умолчанию", callback_data=f"{CB_QCFG_OPEN_PERIOD_OPT}:default")],
                    [InlineKeyboardButton("⚙️ Настроить вручную", callback_data=f"{CB_QCFG_OPEN_PERIOD_OPT}:custom")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data=CB_QCFG_BACK)]
                ]
                open_period_menu_text = f"Время на ответ: не настроено\n\nВыберите действие:"
            
            await query.message.edit_text(
                open_period_menu_text,
                reply_markup=InlineKeyboardMarkup(kb_open_period_options),
                parse_mode=ParseMode.MARKDOWN_V2
            )
            await query.answer()
            return CFG_QUIZ_OPEN_PERIOD_OPTIONS
        elif action.startswith(CB_QCFG_OPEN_PERIOD_OPT):
            opt_type = action.split(":", 1)[1]
            if opt_type == "default":
                # Используем дефолтное значение из настроек чата
                effective_params = await self._get_effective_quiz_params(cfg['chat_id'], cfg['num_questions'])
                open_period_value = effective_params.get('open_period_seconds', 30)
                cfg['open_period_seconds'] = open_period_value
                # Сохраняем настройку в базу данных
                if cfg.get('chat_id'):
                    await self.data_manager.update_quiz_setting(cfg['chat_id'], "open_period_seconds", open_period_value)
                    logger.info(f"Сохранена настройка времени ответа для чата {cfg['chat_id']}: {open_period_value} сек")
                await query.answer("Используется время по умолчанию")
                await self._send_quiz_cfg_message(query, context)
                return CFG_QUIZ_OPTIONS
            elif opt_type == "custom":
                # Показываем поле для ввода значения
                context.chat_data['_editing_open_period'] = True
                await query.message.edit_text(
                    f"Введите время на ответ в секундах \\(от 10 до 300\\):\n\nТекущее значение: {cfg.get('open_period_seconds', 'не настроено')}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=CB_QCFG_BACK)]]),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                await query.answer()
                return CFG_QUIZ_OPEN_PERIOD_INPUT
        elif action.startswith(CB_QCFG_CAT_POOL_MODE):
            # Обработка выбора режима категорий для пользователя
            mode = action.split(":", 1)[1]
            chat_id = cfg.get('chat_id')
            
            logger.info(f"Выбран режим категорий: {mode} для чата {chat_id}")
            
            if chat_id:
                # НЕ применяем режим сразу - только сохраняем во временный контекст
                context.chat_data['_temp_quiz_categories_mode'] = mode
                logger.info(f"Временно сохранен режим категорий: {mode} в контексте")
                
                if mode == "random":
                    # Для случайных категорий спрашиваем количество
                    chat_settings = await self.data_manager.get_chat_settings_async(chat_id)
                    current_val = self.data_manager.get_quiz_setting(chat_id, "num_random_categories", 3)
                    prompt_text = escape_markdown_v2(f"Введите количество случайных категорий (от 1 до 10):\n\nТекущее: {current_val}")
                    
                    # Сохраняем контекст для ввода
                    context.chat_data['_editing_random_categories'] = True
                    context.chat_data['_random_categories_temp'] = current_val
                    
                    # Кнопка "Назад" должна вести к меню выбора категорий
                    kb = [[InlineKeyboardButton("⬅️ Назад", callback_data=CB_QCFG_CAT_MENU)]]
                    await query.message.edit_text(
                        prompt_text,
                        reply_markup=InlineKeyboardMarkup(kb),
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
                    await query.answer()
                    return CFG_QUIZ_NUM_QS
                    
                elif mode == "specific":
                    # Для выбранных категорий показываем список всех категорий
                    # НЕ применяем режим "specific" сразу
                    logger.info(f"Показываем меню выбора категорий для режима: {mode}")
                    await self._show_quiz_categories_pool_menu(query, context)
                    return CFG_QUIZ_OPTIONS
                    
                else:
                    # Для других режимов тоже НЕ применяем сразу
                    await query.answer(f"Режим {mode} выбран (применяется только при сохранении)")
                    await self._send_quiz_cfg_message(query, context)
                    return CFG_QUIZ_OPTIONS
            else:
                await query.answer("Ошибка: не удалось определить чат")
                return CFG_QUIZ_OPTIONS

        elif action.startswith(f"{CB_QCFG_CAT_POOL_SELECT}:"):
            # Обработка выбора/отмены категорий в пуле
            sub_action = action.split(":", 1)[1]
            chat_id = cfg.get('chat_id')
            
            if sub_action in ['save', 'clear']:
                if sub_action == 'clear':
                    if chat_id:
                        # Очищаем пул категорий и снимаем все галочки
                        await self.data_manager.update_chat_setting(chat_id, ["quiz", "specific_categories"], [])
                        
                        # ОБНОВЛЯЕМ: Синхронизируем cfg с очищенными настройками
                        cfg['specific_categories'] = []
                        
                        # НЕ применяем режим "specific" сразу - только при сохранении
                        await query.answer("Пул категорий очищен")
                        # Обновляем меню выбора категорий (НЕ закрываем)
                        await self._show_quiz_categories_pool_menu(query, context)
                        return CFG_QUIZ_OPTIONS
                    else:
                        await query.answer("Ошибка: не удалось определить чат")
                        return CFG_QUIZ_OPTIONS
                else:
                    # Сохраняем изменения в базу данных
                    if chat_id:
                        # Применяем режим "specific" только при сохранении
                        temp_mode = context.chat_data.get('_temp_quiz_categories_mode')
                        if temp_mode == 'specific':
                            await self.data_manager.update_quiz_setting(chat_id, "categories_mode", temp_mode)
                            # Очищаем временный режим
                            context.chat_data.pop('_temp_quiz_categories_mode', None)
                            logger.info(f"Применен режим выбранных категорий при сохранении")
                            
                            # ОБНОВЛЯЕМ: Синхронизируем cfg с примененными настройками
                            cfg['categories_mode'] = temp_mode
                            # Получаем актуальный пул категорий из базы данных
                            current_pool = self.data_manager.get_quiz_setting(chat_id, "specific_categories", [])
                            cfg['specific_categories'] = current_pool
                            
                        await query.answer("Пул категорий сохранен")
                    else:
                        await query.answer("Ошибка: не удалось определить чат")
                        return CFG_QUIZ_OPTIONS
                
                # ОБНОВЛЯЕМ: Синхронизируем cfg с базой данных перед отображением
                if chat_id:
                    cfg['categories_mode'] = self.data_manager.get_quiz_setting(chat_id, "categories_mode", 'random')
                    cfg['num_random_categories'] = self.data_manager.get_quiz_setting(chat_id, "num_random_categories", 3)
                    cfg['specific_categories'] = self.data_manager.get_quiz_setting(chat_id, "specific_categories", [])
                
                # Возвращаемся к основному меню настройки
                await self._send_quiz_cfg_message(query, context)
                return CFG_QUIZ_OPTIONS
            else:
                # Переключение категории
                if chat_id:
                    # Получаем текущий пул категорий из cfg (актуальные данные)
                    current_pool = set(cfg.get('specific_categories', []))
                    
                    # Получаем название категории по короткому ID
                    category_id_map = context.chat_data.get('_quiz_category_id_map', {})
                    original_cat_name = category_id_map.get(sub_action)
                    
                    if not original_cat_name:
                        await query.answer("Ошибка: категория не найдена", show_alert=True)
                        return CFG_QUIZ_OPTIONS
                    
                    if original_cat_name in current_pool:
                        current_pool.remove(original_cat_name)
                        action_text = "убрана из"
                    else:
                        current_pool.add(original_cat_name)
                        action_text = "добавлена в"
                    
                    # Сразу применяем изменения в базу данных
                    await self.data_manager.update_chat_setting(chat_id, ["quiz", "specific_categories"], list(current_pool))
                    
                    # ОБНОВЛЯЕМ: Синхронизируем cfg с изменениями для корректного отображения
                    cfg['specific_categories'] = list(current_pool)
                    
                    # НЕ применяем режим "specific" сразу - только при сохранении
                    await query.answer(f"Категория '{original_cat_name}' {action_text} пул")
                
                # Обновляем меню выбора категорий
                await self._show_quiz_categories_pool_menu(query, context)
                return CFG_QUIZ_OPTIONS

        elif action == CB_QCFG_CANCEL:
            return await self.cancel_quiz_cfg_command(update, context)

        logger.warning(f"Неизвестное действие в handle_quiz_cfg_callback: {action}")
        await query.answer("Неизвестное действие.", show_alert=True)
        return CFG_QUIZ_OPTIONS

    async def handle_typed_num_questions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        if not update.message or not update.message.text:
            return CFG_QUIZ_NUM_QS
        cfg = context.chat_data.get('quiz_cfg_progress')
        if not cfg:
            await update.message.reply_text(escape_markdown_v2("Сессия настройки истекла. Пожалуйста, начните заново командой /quiz."), parse_mode=ParseMode.MARKDOWN_V2)
            return ConversationHandler.END
            
        # Проверяем, что мы редактируем
        if context.chat_data.get('_editing_random_categories'):
            # Редактируем количество случайных категорий
            try:
                num = int(update.message.text.strip())
                if 1 <= num <= 10:
                    chat_id = cfg.get('chat_id')
                    if chat_id:
                        # Применяем количество случайных категорий
                        await self.data_manager.update_quiz_setting(chat_id, "num_random_categories", num)
                        # Применяем режим "random" только при успешном вводе числа
                        temp_mode = context.chat_data.get('_temp_quiz_categories_mode')
                        if temp_mode == 'random':
                            await self.data_manager.update_quiz_setting(chat_id, "categories_mode", temp_mode)
                            # Очищаем временный режим
                            context.chat_data.pop('_temp_quiz_categories_mode', None)
                            logger.info(f"Применен режим случайных категорий с количеством: {num}")
                            
                            # Синхронизируем cfg с примененными настройками
                            cfg['categories_mode'] = temp_mode
                            cfg['num_random_categories'] = num
                            
                        await update.message.reply_text(f"Количество случайных категорий установлено: {num}")
                    context.chat_data.pop('_editing_random_categories', None)
                    try: await update.message.delete()
                    except Exception: pass
                    
                    # Синхронизируем cfg с базой данных перед отображением
                    if chat_id:
                        cfg['categories_mode'] = self.data_manager.get_quiz_setting(chat_id, "categories_mode", 'random')
                        cfg['num_random_categories'] = self.data_manager.get_quiz_setting(chat_id, "num_random_categories", 3)
                    
                    await self._send_quiz_cfg_message(update, context)
                    return CFG_QUIZ_OPTIONS
                else:
                    await update.message.reply_text(escape_markdown_v2(f"Число должно быть от 1 до 10. Попробуйте еще раз или используйте кнопку 'Назад' для отмены."), parse_mode=ParseMode.MARKDOWN_V2, reply_to_message_id=update.message.message_id)
            except ValueError:
                await update.message.reply_text(escape_markdown_v2(f"Это не число. Пожалуйста, введите число от 1 до 10 или используйте кнопку 'Назад' для отмены."), parse_mode=ParseMode.MARKDOWN_V2, reply_to_message_id=update.message.message_id)
            return CFG_QUIZ_NUM_QS
        else:
            # Редактируем количество вопросов - ИСПРАВЛЕНО: сохраняем в базу данных
            try:
                num = int(update.message.text.strip())
                if 1 <= num <= self.app_config.max_questions_per_session:
                    # Сохраняем в базу данных (как и другие настройки)
                    chat_id = cfg.get('chat_id')
                    if chat_id:
                        await self.data_manager.update_quiz_setting(chat_id, "num_questions", num)
                        logger.info(f"Сохранено количество вопросов: {num} для чата {chat_id}")

                    # Обновляем конфигурацию в памяти
                    cfg['num_questions'] = num
                    effective_params_after_num_change = await self._get_effective_quiz_params(cfg['chat_id'], num)
                    cfg['quiz_type_key'] = effective_params_after_num_change['quiz_type_key']
                    cfg['quiz_mode'] = effective_params_after_num_change['quiz_mode']

                    try: await update.message.delete()
                    except Exception: pass
                    await self._send_quiz_cfg_message(update, context)
                    return CFG_QUIZ_OPTIONS
                else:
                    await update.message.reply_text(escape_markdown_v2(f"Число должно быть от 1 до {self.app_config.max_questions_per_session}. Попробуйте еще раз или /{self.app_config.commands.cancel} для отмены."), parse_mode=ParseMode.MARKDOWN_V2, reply_to_message_id=update.message.message_id)
            except ValueError:
                await update.message.reply_text(escape_markdown_v2(f"Это не число. Пожалуйста, введите число или /{self.app_config.commands.cancel} для отмены."), parse_mode=ParseMode.MARKDOWN_V2, reply_to_message_id=update.message.message_id)
            return CFG_QUIZ_NUM_QS

    async def handle_typed_interval_seconds(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        if not update.message or not update.message.text:
            return CFG_QUIZ_INTERVAL_INPUT
        cfg = context.chat_data.get('quiz_cfg_progress')
        if not cfg:
            await update.message.reply_text(escape_markdown_v2("Сессия настройки истекла. Пожалуйста, начните заново командой /quiz."), parse_mode=ParseMode.MARKDOWN_V2)
            return ConversationHandler.END
        
        # Проверяем, что мы действительно редактируем интервал
        if not context.chat_data.get('_editing_interval'):
            await update.message.reply_text(escape_markdown_v2("Ошибка: неожиданный ввод. Пожалуйста, используйте кнопки меню."), parse_mode=ParseMode.MARKDOWN_V2)
            return CFG_QUIZ_OPTIONS
        
        try:
            interval = int(update.message.text.strip())
            if 5 <= interval <= 300:
                cfg['interval_seconds'] = interval
                # Сохраняем настройку в базу данных
                if cfg.get('chat_id'):
                    await self.data_manager.update_quiz_setting(cfg['chat_id'], "interval_seconds", interval)
                    logger.info(f"Сохранена настройка интервала для чата {cfg['chat_id']}: {interval} сек")
                context.chat_data.pop('_editing_interval', None)  # Убираем флаг
                try: await update.message.delete()
                except Exception: pass
                await self._send_quiz_cfg_message(update, context)
                return CFG_QUIZ_OPTIONS
            else:
                await update.message.reply_text(escape_markdown_v2("Интервал должен быть от 5 до 300 секунд. Попробуйте еще раз или используйте кнопку 'Назад' для отмены."), parse_mode=ParseMode.MARKDOWN_V2, reply_to_message_id=update.message.message_id)
        except ValueError:
            await update.message.reply_text(escape_markdown_v2("Это не число. Пожалуйста, введите число от 5 до 300 или используйте кнопку 'Назад' для отмены."), parse_mode=ParseMode.MARKDOWN_V2, reply_to_message_id=update.message.message_id)
        return CFG_QUIZ_INTERVAL_INPUT

    async def handle_typed_open_period_seconds(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        if not update.message or not update.message.text:
            return CFG_QUIZ_OPEN_PERIOD_INPUT
        cfg = context.chat_data.get('quiz_cfg_progress')
        if not cfg:
            await update.message.reply_text(escape_markdown_v2("Сессия настройки истекла. Пожалуйста, начните заново командой /quiz."), parse_mode=ParseMode.MARKDOWN_V2)
            return ConversationHandler.END
        
        # Проверяем, что мы действительно редактируем время ответа
        if not context.chat_data.get('_editing_open_period'):
            await update.message.reply_text(escape_markdown_v2("Ошибка: неожиданный ввод. Пожалуйста, используйте кнопки меню."), parse_mode=ParseMode.MARKDOWN_V2)
            return CFG_QUIZ_OPTIONS
        
        try:
            open_period = int(update.message.text.strip())
            if 10 <= open_period <= 300:
                cfg['open_period_seconds'] = open_period
                # Сохраняем настройку в базу данных
                if cfg.get('chat_id'):
                    await self.data_manager.update_quiz_setting(cfg['chat_id'], "open_period_seconds", open_period)
                    logger.info(f"Сохранена настройка времени ответа для чата {cfg['chat_id']}: {open_period} сек")
                context.chat_data.pop('_editing_open_period', None)  # Убираем флаг
                try: await update.message.delete()
                except Exception: pass
                await self._send_quiz_cfg_message(update, context)
                return CFG_QUIZ_OPTIONS
            else:
                await update.message.reply_text(escape_markdown_v2("Время на ответ должно быть от 10 до 300 секунд. Попробуйте еще раз или используйте кнопку 'Назад' для отмены."), parse_mode=ParseMode.MARKDOWN_V2, reply_to_message_id=update.message.message_id)
        except ValueError:
            await update.message.reply_text(escape_markdown_v2("Это не число. Пожалуйста, введите число от 10 до 300 или используйте кнопку 'Назад' для отмены."), parse_mode=ParseMode.MARKDOWN_V2, reply_to_message_id=update.message.message_id)
        return CFG_QUIZ_OPEN_PERIOD_INPUT

    async def cancel_quiz_cfg_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        final_message_text = escape_markdown_v2("Настройка викторины отменена.")
        quiz_cfg_msg_id = context.chat_data.pop('_quiz_cfg_msg_id', None)
        original_cmd_msg_id = context.chat_data.get('_quiz_cmd_msg_id')
        cfg_progress_data = context.chat_data.pop('quiz_cfg_progress', None)

        chat_id_for_ops: Optional[int] = None
        if cfg_progress_data and 'chat_id' in cfg_progress_data: chat_id_for_ops = cfg_progress_data['chat_id']
        elif query and query.message: chat_id_for_ops = query.message.chat_id
        elif update.message and update.message.chat: chat_id_for_ops = update.message.chat.id
        elif update.effective_chat: chat_id_for_ops = update.effective_chat.id

        if query:
            await query.answer()
            if query.message and quiz_cfg_msg_id == query.message.message_id and quiz_cfg_msg_id != original_cmd_msg_id:
                try: await query.edit_message_text(final_message_text, reply_markup=None, parse_mode=ParseMode.MARKDOWN_V2)
                except Exception: pass
            elif chat_id_for_ops:
                 if quiz_cfg_msg_id and quiz_cfg_msg_id != original_cmd_msg_id:
                     deletion_success = False
                     try:
                         await context.bot.delete_message(chat_id_for_ops, quiz_cfg_msg_id)
                         deletion_success = True
                     except Exception:
                         pass
                     # ФАЛБЭК: Если не удалось удалить сразу, добавляем в систему автоудаления
                     if not deletion_success:
                         self.state.add_message_for_deletion(chat_id_for_ops, quiz_cfg_msg_id, delay_seconds=10)
                 try:
                     cancel_msg = await safe_send_message(
                         bot=context.bot,
                         chat_id=chat_id_for_ops,
                         text=final_message_text,
                         parse_mode=ParseMode.MARKDOWN_V2
                     )
                     # Добавляем сообщение об отмене в автоудаление (20 сек)
                     if cancel_msg:
                         self.state.add_message_for_deletion(chat_id_for_ops, cancel_msg.message_id, delay_seconds=20)
                 except Exception:
                     pass
        elif update.message:
            if chat_id_for_ops:
                if quiz_cfg_msg_id and quiz_cfg_msg_id != original_cmd_msg_id:
                    deletion_success = False
                    try:
                        await context.bot.delete_message(chat_id_for_ops, quiz_cfg_msg_id)
                        deletion_success = True
                    except Exception:
                        pass
                    # ФАЛБЭК: Если не удалось удалить сразу, добавляем в систему автоудаления
                    if not deletion_success:
                        self.state.add_message_for_deletion(chat_id_for_ops, quiz_cfg_msg_id, delay_seconds=10)
                try:
                    cancel_msg = await safe_send_message(
                        bot=context.bot,
                        chat_id=chat_id_for_ops,
                        text=final_message_text,
                        parse_mode=ParseMode.MARKDOWN_V2,
                        reply_to_message_id=update.message.message_id
                    )
                    # Добавляем сообщение об отмене в автоудаление (20 сек)
                    if cancel_msg:
                        self.state.add_message_for_deletion(chat_id_for_ops, cancel_msg.message_id, delay_seconds=20)
                except Exception:
                    pass
            elif update.effective_chat:
                try: await update.effective_chat.send_message(final_message_text, parse_mode=ParseMode.MARKDOWN_V2)
                except Exception: pass

        context.chat_data.clear()
        return ConversationHandler.END

    async def stop_quiz_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or not update.effective_user or not update.message:
            return
        chat_id = update.effective_chat.id
        user_who_stopped = update.effective_user
        logger.info(f"Команда /{self.app_config.commands.stop_quiz} вызвана пользователем {user_who_stopped.id} ({user_who_stopped.full_name}) в чате {chat_id}.")
        if self._pg_sessions:
            from application.classic import ClassicApplicationService
            database = self._pg_sessions.database
            can_administer = await is_user_admin_in_update(update, context)
            try:
                async with database.transaction() as session:
                    service = ClassicApplicationService(database, session)
                    current = await service.current(
                        chat_id=chat_id, user_id=user_who_stopped.id,
                    )
                    if current is None:
                        raise LookupError('Нет активной викторины для остановки.')
                    await service.stop(
                        chat_id=chat_id,
                        user_id=user_who_stopped.id,
                        expected_revision=current['revision'],
                        command_id=f'tg-stop:{chat_id}:{update.message.message_id}',
                        allow_admin=can_administer,
                    )
            except (LookupError, PermissionError, RuntimeError, ValueError) as error:
                await update.message.reply_text(
                    escape_markdown_v2(str(error)), parse_mode=ParseMode.MARKDOWN_V2,
                )
                return
            await update.message.reply_text(
                escape_markdown_v2(
                    f'Викторина остановлена пользователем {user_who_stopped.first_name}.'
                ),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return
        quiz_state = self.state.get_active_quiz(chat_id)
        if not quiz_state:
            await update.message.reply_text(escape_markdown_v2("Нет активной викторины для остановки."), parse_mode=ParseMode.MARKDOWN_V2)
            return
        if quiz_state.is_stopping:
            await update.message.reply_text(escape_markdown_v2("Викторина уже в процессе остановки."), parse_mode=ParseMode.MARKDOWN_V2)
            return
        can_stop = await is_user_admin_in_update(update, context)
        if not can_stop and quiz_state.created_by_user_id == user_who_stopped.id and quiz_state.quiz_type != "daily":
            can_stop = True
        if not can_stop:
            await update.message.reply_text(escape_markdown_v2("Только администраторы чата или инициатор (кроме ежедневной викторины) могут остановить текущую викторину."), parse_mode=ParseMode.MARKDOWN_V2)
            return

        quiz_state.is_stopping = True
        stop_confirm_msg = await update.message.reply_text(f"Викторина остановлена пользователем {escape_markdown_v2(user_who_stopped.first_name)}\\. Подведение итогов\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
        quiz_state.message_ids_to_delete.add(stop_confirm_msg.message_id) 

        await self._finalize_quiz_session(context, chat_id, was_stopped=True)

    def get_handlers(self) -> list:
        from modules.telegram_menu import conversation_entry, home_fallbacks
        cancel_handler_for_conv = CommandHandler(self.app_config.commands.cancel, self.cancel_quiz_cfg_command)
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler(self.app_config.commands.quiz, self.quiz_command_entry),
                CallbackQueryHandler(conversation_entry(self.quiz_command_entry, self.app_config.commands.quiz), pattern=r'^(nav:quiz|start_quiz)$'),
                CommandHandler('start', conversation_entry(self.quiz_command_entry, self.app_config.commands.quiz), filters=filters.Regex(r'^/start(?:@\w+)? (?:quiz|play)$'))],
            states={
                CFG_QUIZ_OPTIONS: [CallbackQueryHandler(self.handle_quiz_cfg_callback, pattern=f"^{CB_QCFG_}")],
                CFG_QUIZ_NUM_QS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_typed_num_questions),
                    CallbackQueryHandler(self.handle_quiz_cfg_callback, pattern=f"^{CB_QCFG_}")
                ],
                CFG_QUIZ_INTERVAL_OPTIONS: [CallbackQueryHandler(self.handle_quiz_cfg_callback, pattern=f"^{CB_QCFG_}")],
                CFG_QUIZ_INTERVAL_INPUT: [
                    CallbackQueryHandler(self.handle_quiz_cfg_callback, pattern=f"^{CB_QCFG_}"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_typed_interval_seconds)
                ],
                CFG_QUIZ_OPEN_PERIOD_OPTIONS: [CallbackQueryHandler(self.handle_quiz_cfg_callback, pattern=f"^{CB_QCFG_}")],
                CFG_QUIZ_OPEN_PERIOD_INPUT: [
                    CallbackQueryHandler(self.handle_quiz_cfg_callback, pattern=f"^{CB_QCFG_}"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_typed_open_period_seconds)
                ],
            },
            fallbacks=[*home_fallbacks(), cancel_handler_for_conv],
            per_chat=True, per_user=True, name="quiz_interactive_setup_conv", persistent=True, allow_reentry=True
        )
        return [
            conv_handler,  # ConversationHandler уже обрабатывает команду /quiz
            # УБИРАЕМ дублирующий CommandHandler для /quiz - он уже есть в ConversationHandler
            CommandHandler(self.app_config.commands.stop_quiz, self.stop_quiz_command),
            CommandHandler(self.app_config.commands.reset_categories_stats, self.reset_categories_stats_command),
            CommandHandler(self.app_config.commands.chat_stats, self.chat_stats_command),
            CommandHandler("scheduler_status", self.scheduler_status_command)
        ]



    async def reset_categories_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Команда для сброса статистики использования категорий (только для администраторов)"""
        if not update.message or not update.effective_chat:
            return
        
        # Проверяем права администратора
        if not await is_user_admin_in_update(update, context):
            await update.message.reply_text(
                escape_markdown_v2("❌ У вас нет прав для выполнения этой команды. Требуются права администратора.")
            )
            return
        
        chat_id = update.effective_chat.id
        user = update.effective_user
        logger.info(f"Сброс статистики категорий запрошен пользователем {user.id} ({user.full_name}) в чате {chat_id}")
        
        try:
            # Сбрасываем статистику
            if self._pg_sessions:
                from storage.category_statistics import CategoryStatistics
                from uuid import uuid4
                service = CategoryStatistics(self._pg_sessions.database)
                preview = await service.preview(chat_id)
                await service.reset_chat(chat_id, expected_version=preview['version'], confirmation=str(chat_id), action_id=str(uuid4()))
                await self.category_manager.refresh_postgres_statistics()
            else:
                self.category_manager.reset_category_usage_stats()
            
            await update.message.reply_text(
                escape_markdown_v2("✅ Статистика использования категорий успешно сброшена.\n\n"
                                "Теперь при проведении викторин будет накапливаться новая корректная статистика.")
            )
            
        except Exception as e:
            logger.error(f"Ошибка при сбросе статистики категорий: {e}", exc_info=True)
            await update.message.reply_text(
                escape_markdown_v2("❌ Произошла ошибка при сбросе статистики категорий.")
            )

    async def _show_quiz_categories_pool_menu(self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
        """Показывает меню управления пулом категорий для пользователя"""
        cfg = context.chat_data.get('quiz_cfg_progress')
        if not cfg:
            await query.answer("Ошибка: сессия настройки истекла")
            return
            
        chat_id = cfg.get('chat_id')
        if not chat_id:
            await query.answer("Ошибка: не удалось определить чат")
            return
            
        # Получаем текущий пул категорий из cfg (актуальные данные)
        current_pool = set(cfg.get('specific_categories', []))
        
        # СИНХРОНИЗИРУЕМ: Обновляем cfg из базы данных для актуальности
        if chat_id:
            cfg['specific_categories'] = self.data_manager.get_quiz_setting(chat_id, "specific_categories", [])
            current_pool = set(cfg['specific_categories'])
        
        all_categories = self.category_manager.get_all_category_names(with_question_counts=False)
        
        # Создаем кнопки для каждой категории с переключателями
        kb = []
        category_id_map = {}
        context.chat_data['_quiz_category_id_map'] = category_id_map
        
        for i, cat_name in enumerate(sorted(all_categories)):
            if isinstance(cat_name, str):
                prefix = "✅ " if cat_name in current_pool else "☑️ "
                # Используем короткие ID как в ежедневной викторине
                short_cat_id = f"qc{i}"
                category_id_map[short_cat_id] = cat_name
                
                button_text = cat_name
                if len(button_text) > 30:
                    button_text = button_text[:27] + "..."
                
                # Валидируем callback_data для безопасности
                safe_callback_data = self._validate_callback_data(f"{CB_QCFG_CAT_POOL_SELECT}:{short_cat_id}")
                kb.append([InlineKeyboardButton(f"{prefix}{button_text}", callback_data=safe_callback_data)])
        
        # Кнопки управления
        kb.append([
            InlineKeyboardButton("💾 Сохранить", callback_data=f"{CB_QCFG_CAT_POOL_SELECT}:save"),
            InlineKeyboardButton("🗑️ Очистить", callback_data=f"{CB_QCFG_CAT_POOL_SELECT}:clear")
        ])
        # Кнопка "Назад" должна вести к меню выбора режима категорий
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data=CB_QCFG_BACK)])
        
        current_pool_display = ', '.join(sorted([cat.strip() for cat in current_pool if cat and cat.strip()])) if current_pool else 'пусто'
        text = (
            f"📝 Выбор категорий для викторины\n\n"
            f"🎯 Текущий выбор: {escape_markdown_v2(current_pool_display)}\n\n"
            f"{escape_markdown_v2('Выберите категории для включения в викторину:')}"
        )
        
        try:
            await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN_V2)
        except BadRequest as e_br:
            # Если сообщение не изменилось - это нормальная ситуация (например, двойной клик)
            if "Message is not modified" not in str(e_br).lower():
                logger.warning(f"Ошибка BadRequest при редактировании меню выбора категорий: {e_br}")
            # В любом случае отвечаем на callback
            await query.answer()
        except Exception as e_edit:
            logger.error(f"Не удалось обновить меню выбора категорий: {e_edit}")
            await query.answer("Ошибка обновления меню", show_alert=True)

    async def chat_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Команда для просмотра статистики викторин по чатам"""
        if not update.message or not update.effective_chat:
            return
        
        chat_id = update.effective_chat.id
        logger.info(f"Статистика викторин по чатам запрошена в чате {chat_id}")
        
        try:
            # ИСПРАВЛЕНО: Получаем статистику пользователей в этом чате из data_manager
            chat_id_str = str(chat_id)
            if self.data_manager.postgres_storage:
                from storage.score_queries import ScoreQueries
                snapshot = await ScoreQueries(self.data_manager.postgres_storage.database).chat_statistics(chat_id)
                chat_user_scores, category_stats = snapshot["users"], snapshot["categories"]
            else:
                chat_users_file = self.data_manager.chats_dir / chat_id_str / "users.json"
                chat_user_scores = {}
                if chat_users_file.exists():
                    with open(chat_users_file, 'r', encoding='utf-8') as f:
                        chat_user_scores = json.load(f)
                category_stats = self.category_manager.get_category_usage_stats(read_only=True)
            
            # Подсчитываем статистику по чату
            total_users_in_chat = len(chat_user_scores)
            total_score_in_chat = sum(user_data.get('score', 0) for user_data in chat_user_scores.values())
            total_answered_polls = sum(user_data.get('answered_count', len(user_data.get('answered_polls', set()))) for user_data in chat_user_scores.values())
            
            # Статистика категорий в этом чате
            chat_category_usage = {}
            for cat_name, cat_stats in category_stats.items():
                # ИСПРАВЛЕНО: Проверяем, что chat_usage является словарем
                chat_usage_data = cat_stats.get('chat_usage', {})
                if isinstance(chat_usage_data, dict):
                    chat_usage = chat_usage_data.get(chat_id_str, 0)
                    if chat_usage > 0:
                        chat_category_usage[cat_name] = chat_usage
            
            # Сортируем категории по использованию в чате
            sorted_chat_categories = sorted(chat_category_usage.items(), key=lambda x: x[1], reverse=True)
            
            # Формируем ответ
            response_text = escape_markdown_v2(f"📊 Статистика викторин в чате\n\n")
            
            # Общая статистика чата
            response_text += escape_markdown_v2("🏆 Общая статистика чата:\n")
            response_text += escape_markdown_v2(f"• Участников: {total_users_in_chat}\n")
            # ИСПРАВЛЕНО: Округляем общий рейтинг до 1 знака после запятой
            response_text += escape_markdown_v2(f"• Общий рейтинг: {round(total_score_in_chat, 1)}\n")
            response_text += escape_markdown_v2(f"• Всего ответов: {total_answered_polls}\n\n")
            
            # Топ пользователей в чате
            if chat_user_scores:
                response_text += escape_markdown_v2("👥 Топ участников:\n")
                sorted_users = sorted(chat_user_scores.items(), key=lambda x: x[1].get('score', 0), reverse=True)
                for i, (user_id, user_data) in enumerate(sorted_users[:5], 1):
                    user_name = user_data.get('name', f'User {user_id}')
                    user_score = user_data.get('score', 0)
                    user_answered = len(user_data.get('answered_polls', set()))
                    # ИСПРАВЛЕНО: Округляем очки пользователя до 1 знака после запятой
                    response_text += escape_markdown_v2(f"{i}. {user_name}: {round(user_score, 1)} очков ({user_answered} ответов)\n")
                response_text += "\n"
            
            # Статистика категорий в чате
            if chat_category_usage:
                response_text += escape_markdown_v2("📚 Использование категорий в чате:\n")
                for i, (cat_name, usage_count) in enumerate(sorted_chat_categories[:10], 1):
                    response_text += escape_markdown_v2(f"{i}. {cat_name}: {usage_count} раз\n")
            else:
                response_text += escape_markdown_v2("📚 Категории в этом чате еще не использовались\n")
            
            await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)
            
        except Exception as e:
            logger.error(f"Ошибка при получении статистики чата: {e}", exc_info=True)
            await update.message.reply_text(escape_markdown_v2("Произошла ошибка при получении статистики чата."))

    def _validate_callback_data(self, callback_data: str) -> str:
        """Валидирует и очищает callback_data от недопустимых символов"""
        # Убираем все символы, кроме букв, цифр, подчеркиваний, двоеточий и дефисов
        cleaned = re.sub(r'[^a-zA-Z0-9_:.-]', '', callback_data)
        # Ограничиваем длину
        if len(cleaned) > 64:
            cleaned = cleaned[:64]
        return cleaned

    async def scheduler_status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Команда для проверки статуса планировщика ежедневных викторин (только для администраторов)"""
        if not update.message or not update.effective_chat:
            return
        
        # Проверяем права администратора
        if not await is_user_admin_in_update(update, context):
            await update.message.reply_text(
                escape_markdown_v2("❌ У вас нет прав для выполнения этой команды. Требуются права администратора.")
            )
            return
        
        chat_id = update.effective_chat.id
        user = update.effective_user
        logger.info(f"Проверка статуса планировщика запрошена пользователем {user.id} ({user.full_name}) в чате {chat_id}")
        
        try:
            logger.debug(f"Начинаем получение статуса планировщика для чата {chat_id}")
            
            # Получаем статус планировщика из quiz_manager (который получает его при создании)
            scheduler = getattr(self, 'daily_quiz_scheduler', None)
            
            if not scheduler:
                await update.message.reply_text(
                    escape_markdown_v2("❌ Планировщик ежедневных викторин недоступен\\.")
                )
                return
            
            status = scheduler.get_scheduler_status()
            
            if "error" in status:
                await update.message.reply_text(
                    escape_markdown_v2(f"❌ Ошибка получения статуса планировщика: {status['error']}")
                )
                return
            
            # Формируем ответ - используем escape_markdown_v2 для всех переменных
            response_text = "📊 *Статус планировщика ежедневных викторин:*\n\n"
            response_text += f"🔧 Всего задач в системе: {escape_markdown_v2(str(status['total_jobs']))}\n"
            response_text += f"🎯 Задач ежедневных викторин: {escape_markdown_v2(str(status['daily_quiz_jobs']))}\n"
            response_text += f"⚡ Планировщик работает: {escape_markdown_v2('Да' if status['scheduler_working'] else 'Нет')}\n\n"
            
            if status['daily_quiz_jobs_details']:
                response_text += "📋 *Детали задач ежедневных викторин:*\n\n"
                
                # Группируем задачи по чатам
                chat_jobs = {}
                for job_detail in status['daily_quiz_jobs_details']:
                    # Извлекаем chat_id из имени задачи
                    chat_id = None
                    try:
                        # Формат: daily_quiz_for_chat_{chat_id}_time_idx_{time_index}
                        match = re.search(r'daily_quiz_for_chat_(-?\d+)_time_idx_', job_detail['name'])
                        if match:
                            chat_id = int(match.group(1))
                    except (ValueError, AttributeError):
                        pass
                    
                    if chat_id not in chat_jobs:
                        chat_jobs[chat_id] = []
                    chat_jobs[chat_id].append(job_detail)
                
                # Выводим задачи, сгруппированные по чатам
                for chat_id, jobs in chat_jobs.items():
                    # Получаем информацию о чате
                    chat_title = "Неизвестный чат"
                    chat_type = "неизвестно"
                    if chat_id:
                        try:
                            chat = await context.bot.get_chat(chat_id)
                            chat_title = chat.title or chat.first_name or f"Чат {chat_id}"
                            
                            # Определяем тип чата
                            if chat.type == "private":
                                chat_type = "личный чат"
                            elif chat.type == "group":
                                chat_type = "группа"
                            elif chat.type == "supergroup":
                                chat_type = "супергруппа"
                            elif chat.type == "channel":
                                chat_type = "канал"
                            else:
                                chat_type = chat.type
                                
                        except Exception as e:
                            logger.debug(f"Не удалось получить информацию о чате {chat_id}: {e}")
                            chat_title = f"Чат {chat_id}"
                            chat_type = "неизвестно"
                    
                    # Заголовок чата - экранируем все специальные символы для Markdown V2
                    safe_chat_title = escape_markdown_v2(chat_title)
                    safe_chat_type = escape_markdown_v2(chat_type)
                    
                    # Логируем для отладки
                    logger.debug(f"Chat title: '{chat_title}' -> safe: '{safe_chat_title}'")
                    logger.debug(f"Chat type: '{chat_type}' -> safe: '{safe_chat_type}'")
                    
                    response_text += f"📱 *{safe_chat_title}* \\(ID: {escape_markdown_v2(str(chat_id))}\\)\n"
                    response_text += f"   🏷️ Тип: {safe_chat_type}\n"
                    response_text += f"   📅 Расписание:\n"
                    
                    # Сортируем задачи по времени (MSK)
                    sorted_jobs = sorted(jobs, key=lambda x: x['next_run_moscow'])
                    
                    for job_detail in sorted_jobs:
                        status_icon = "✅" if job_detail['enabled'] else "❌"
                        
                        # ИСПРАВЛЕНИЕ: Показываем время, которое планировщик уже правильно вычислил
                        # Планировщик работает корректно, проблема только в отображении
                        moscow_time_str = job_detail['next_run_moscow']
                        
                        # Логируем для отладки
                        logger.debug(f"Job {job_detail['name']}: показываем время: {moscow_time_str}")
                        
                        # Экранируем время для Markdown V2
                        moscow_time_escaped = escape_markdown_v2(moscow_time_str)
                        
                        response_text += f"      {status_icon} {moscow_time_escaped}\n"
                    
                    response_text += "\n"
            else:
                response_text += "⚠️ Нет запланированных задач ежедневных викторин\n"
            
            # Добавляем текущее время для справки
            from datetime import datetime
            import pytz
            now_utc = datetime.now(pytz.UTC)
            now_moscow = now_utc.astimezone(pytz.timezone('Europe/Moscow'))
            
            # Логируем для отладки
            logger.debug(f"Текущее время: UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}, MSK: {now_moscow.strftime('%Y-%m-%d %H:%M:%S')}")
            
            response_text += "⏰ *Текущее время:*\n"
            response_text += f"   {escape_markdown_v2(now_moscow.strftime('%Y-%m-%d %H:%M:%S'))}"
            
            await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)
            
        except Exception as e:
            logger.error(f"Ошибка при получении статуса планировщика: {e}", exc_info=True)
            await update.message.reply_text(
                escape_markdown_v2("❌ Произошла ошибка при получении статуса планировщика.")
            )

    # ===== СИСТЕМА ВОССТАНОВЛЕНИЯ АКТИВНЫХ ВИКТОРИН =====

    def restore_quiz_from_saved_data(self, chat_id: int, quiz_data: Dict[str, Any]) -> Optional[QuizState]:
        """
        Восстанавливает викторину из сохраненных данных.
        Возвращает восстановленный QuizState или None в случае ошибки.
        """
        try:
            from datetime import datetime

            # Создаем новый QuizState из сохраненных данных
            restored_quiz = QuizState(
                chat_id=quiz_data["chat_id"],
                quiz_type=quiz_data["quiz_type"],
                quiz_mode=quiz_data["quiz_mode"],
                questions=quiz_data["questions"],
                num_questions_to_ask=quiz_data["num_questions_to_ask"],
                open_period_seconds=quiz_data["open_period_seconds"],
                created_by_user_id=quiz_data.get("created_by_user_id"),
                original_command_message_id=quiz_data.get("original_command_message_id"),
                announce_message_id=quiz_data.get("announce_message_id"),
                interval_seconds=quiz_data.get("interval_seconds"),
                quiz_start_time=datetime.fromisoformat(quiz_data["quiz_start_time"]) if quiz_data.get("quiz_start_time") else None
            )

            # Восстанавливаем состояние викторины
            restored_quiz.current_question_index = quiz_data["current_question_index"]
            restored_quiz.scores = quiz_data["scores"]
            restored_quiz.active_poll_ids_in_session = set(quiz_data["active_poll_ids_in_session"])
            restored_quiz.latest_poll_id_sent = quiz_data.get("latest_poll_id_sent")
            restored_quiz.progression_triggered_for_poll = quiz_data["progression_triggered_for_poll"]
            restored_quiz.message_ids_to_delete = set(quiz_data["message_ids_to_delete"])
            restored_quiz.is_stopping = quiz_data["is_stopping"]
            restored_quiz.poll_and_solution_message_ids = quiz_data["poll_and_solution_message_ids"]
            restored_quiz.results_message_ids = set(quiz_data.get("results_message_ids", []))

            logger.info(f"✅ Викторина чата {chat_id} успешно восстановлена")
            return restored_quiz

        except Exception as e:
            logger.error(f"❌ Ошибка восстановления викторины чата {chat_id}: {e}", exc_info=True)
            return None

    async def notify_users_about_restored_quiz(self, chat_id: int, quiz_state: QuizState) -> None:
        """
        Уведомляет пользователей в чате о восстановленной викторине после перезапуска бота.
        """
        try:
            # Формируем сообщение о восстановлении
            current_question = quiz_state.current_question_index + 1
            total_questions = quiz_state.num_questions_to_ask
            quiz_type_text = "одиночная" if quiz_state.quiz_type == "single" else "сессионная"

            message_text = f"""🤖 *Бот был перезапущен*

🎯 **Восстановлена {quiz_type_text} викторина!**

📊 *Прогресс:* {current_question}/{total_questions} вопросов
⏱️ *Тип:* {quiz_state.quiz_mode.replace('_', ' ').title()}
👥 *Участников:* {len(quiz_state.scores)}

🔄 Викторина продолжается с того места, где остановилась.
Используйте /stopquiz для остановки или просто продолжайте отвечать!

_Если вы хотите начать новую викторину, сначала остановите текущую командой /stopquiz_"""

            await self.application.bot.send_message(
                chat_id=chat_id,
                text=escape_markdown_v2(message_text),
                parse_mode=ParseMode.MARKDOWN_V2
            )

            logger.info(f"✅ Отправлено уведомление о восстановленной викторине в чат {chat_id}")

        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления о восстановленной викторине в чат {chat_id}: {e}")

    async def restore_all_active_quizzes(self) -> None:
        """
        Восстанавливает все активные викторины из сохраненных данных.
        Вызывается при запуске бота.
        """
        if self._pg_sessions:
            await self._restore_postgres_classic()
            return
        try:
            # Загружаем сохраненные викторины
            saved_quizzes = self.data_manager.load_active_quizzes()

            if not saved_quizzes:
                logger.info("Нет сохраненных викторин для восстановления")
                return

            restored_count = 0

            for chat_id, quiz_data in saved_quizzes.items():
                try:
                    # Восстанавливаем викторину
                    restored_quiz = self.restore_quiz_from_saved_data(chat_id, quiz_data)

                    if restored_quiz:
                        # Добавляем в активные викторины
                        self.state.add_active_quiz(chat_id, restored_quiz)

                        # Уведомляем пользователей
                        await self.notify_users_about_restored_quiz(chat_id, restored_quiz)

                        restored_count += 1
                        logger.info(f"Восстановлена викторина чата {chat_id}")

                    else:
                        logger.warning(f"Не удалось восстановить викторину чата {chat_id}")

                except Exception as e:
                    logger.error(f"Ошибка при восстановлении викторины чата {chat_id}: {e}", exc_info=True)
                    continue

            if restored_count > 0:
                logger.info(f"✅ Восстановлено {restored_count} активных викторин")
                # Удаляем файл после успешного восстановления
                self.data_manager.delete_active_quizzes_file()
            else:
                logger.info("Не удалось восстановить ни одной викторины")

        except Exception as e:
            logger.error(f"❌ Ошибка при восстановлении активных викторин: {e}", exc_info=True)

    def schedule_quiz_auto_save(self) -> None:
        """
        Настраивает автоматическое сохранение активных викторин.
        Вызывается при запуске бота.
        """
        if self._pg_sessions:
            return  # Each PostgreSQL transition already awaits its own checkpoint.
        try:
            # Создаем job для периодического сохранения (каждые 5 минут)
            job_name = "auto_save_active_quizzes"

            # Удаляем существующий job если есть
            if self.application.job_queue:
                existing_jobs = self.application.job_queue.get_jobs_by_name(job_name)
                for job in existing_jobs:
                    job.schedule_removal()

                # Создаем новый job
                self.application.job_queue.run_repeating(
                    callback=self._auto_save_quizzes_job,
                    interval=300,  # 5 минут
                    first=60,     # Первый запуск через 1 минуту
                    name=job_name
                )

                logger.info("✅ Настроено автоматическое сохранение активных викторин (каждые 5 минут)")

        except Exception as e:
            logger.error(f"❌ Ошибка настройки автоматического сохранения викторин: {e}")

    async def _auto_save_quizzes_job(self, context) -> None:
        """
        Job для автоматического сохранения активных викторин.
        """
        try:
            if hasattr(self.data_manager, 'save_active_quizzes'):
                self.data_manager.save_active_quizzes()
                logger.debug("Автоматически сохранены активные викторины")
        except Exception as e:
            logger.error(f"Ошибка автоматического сохранения викторин: {e}")
