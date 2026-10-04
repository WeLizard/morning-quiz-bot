#handlers/config_handlers.py
from __future__ import annotations
import logging
import asyncio
from typing import TYPE_CHECKING, List, Any, Optional, Dict, Union, Set

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ConversationHandler, Application
)
from telegram.constants import ParseMode
from telegram.error import BadRequest

if TYPE_CHECKING:
    from app_config import AppConfig
    from data_manager import DataManager
    from .wisdom_scheduler import WisdomScheduler

from modules.category_manager import CategoryManager
from utils import is_user_admin_in_update, escape_markdown_v2, pluralize, format_seconds_to_human_readable_time, add_admin_to_config
from modules.telegram_utils import safe_send_message
from .daily_quiz_scheduler import DailyQuizScheduler
from .wisdom_scheduler import WisdomScheduler

logger = logging.getLogger(__name__)

CFG_MAIN_MENU = 'cfg_main_menu'
CFG_INPUT_VALUE = 'cfg_input_value'
CFG_SELECT_GENERAL_CATEGORIES = 'cfg_select_general_categories'
CFG_DAILY_MENU = 'cfg_daily_menu'
CFG_CONFIRM_RESET = 'cfg_confirm_reset'
CFG_DAILY_TIMES_MENU = 'cfg_daily_times_menu'
CFG_DAILY_ADD_TIME = 'cfg_daily_add_time'
CFG_DAILY_TIMEZONE_MENU = 'cfg_daily_timezone_menu'
CFG_QUIZ_MENU = 'cfg_quiz_menu'
CFG_QUIZ_CATEGORIES_MENU = 'cfg_quiz_categories_menu'
CFG_QUIZ_CATEGORIES_POOL_SELECTION = 'cfg_quiz_categories_pool_selection'
CFG_WISDOM_MENU = 'cfg_wisdom_menu'
CFG_WISDOM_TIME_INPUT = 'cfg_wisdom_time_input'
CFG_WISDOM_TIMEZONE_MENU = 'cfg_wisdom_timezone_menu'

CB_ADM_ = "admcfg_"
CB_ADM_BACK_TO_MAIN = f"{CB_ADM_}back_to_main"
CB_ADM_BACK_TO_DAILY_MENU = f"{CB_ADM_}back_to_daily_menu"
CB_ADM_BACK_TO_QUIZ_MENU = f"{CB_ADM_}back_to_quiz_menu"
CB_ADM_FINISH_CONFIG = f"{CB_ADM_}finish"
CB_ADM_CONFIRM_RESET_SETTINGS = f"{CB_ADM_}confirm_reset"
CB_ADM_EXECUTE_RESET_SETTINGS = f"{CB_ADM_}execute_reset"
CB_ADM_SET_DEFAULT_QUIZ_TYPE = f"{CB_ADM_}set_def_q_type"
CB_ADM_SET_DEFAULT_QUIZ_TYPE_OPT = f"{CB_ADM_}set_def_q_type_opt"
CB_ADM_SET_DEFAULT_NUM_QUESTIONS = f"{CB_ADM_}set_def_num_q"
CB_ADM_SET_DEFAULT_NUM_CATEGORIES = f"{CB_ADM_}set_def_num_cat"
CB_ADM_SET_DEFAULT_OPEN_PERIOD = f"{CB_ADM_}set_def_open_per"
CB_ADM_SET_DEFAULT_ANNOUNCE_QUIZ = f"{CB_ADM_}set_def_ann_q"
CB_ADM_WISDOM_MENU = f"{CB_ADM_}wisdom_menu"
CB_ADM_WISDOM_TOGGLE = f"{CB_ADM_}wisdom_toggle"
CB_ADM_WISDOM_SET_TIME = f"{CB_ADM_}wisdom_set_time"
CB_ADM_WISDOM_SET_TIMEZONE = f"{CB_ADM_}wisdom_set_timezone"
CB_ADM_WISDOM_BACK_TO_MAIN = f"{CB_ADM_}wisdom_back_to_main"
CB_ADM_WISDOM_ = f"{CB_ADM_}wisdom_"
CB_ADM_SET_DEFAULT_ANNOUNCE_QUIZ_OPT = f"{CB_ADM_}set_def_ann_q_opt"
CB_ADM_SET_DEFAULT_ANNOUNCE_DELAY = f"{CB_ADM_}set_def_ann_d"
CB_ADM_MANAGE_ENABLED_CATEGORIES = f"{CB_ADM_}manage_en_cats"
CB_ADM_MANAGE_DISABLED_CATEGORIES = f"{CB_ADM_}manage_dis_cats"
CB_ADM_CAT_SEL_ = f"{CB_ADM_}g_cat_sel_"
CB_ADM_CAT_TOGGLE = f"{CB_ADM_CAT_SEL_}toggle"
CB_ADM_CAT_SAVE_SELECTION = f"{CB_ADM_CAT_SEL_}save"
CB_ADM_CAT_CLEAR_SELECTION = f"{CB_ADM_CAT_SEL_}clear"
CB_ADM_GOTO_DAILY_MENU = f"{CB_ADM_}goto_daily_menu"
CB_ADM_GOTO_QUIZ_MENU = f"{CB_ADM_}goto_quiz_menu"
CB_ADM_GOTO_QUIZ_CATEGORIES_MENU = f"{CB_ADM_}goto_quiz_categories_menu"
CB_ADM_BACK_TO_QUIZ_CATEGORIES_MENU = f"{CB_ADM_}quiz_categories_menu_back"
CB_ADM_BACK_TO_DAILY_MENU = f"{CB_ADM_}daily_menu_back"
CB_ADM_DAILY_TOGGLE_ENABLED = f"{CB_ADM_}daily_toggle_en"
CB_ADM_DAILY_MANAGE_TIMES = f"{CB_ADM_}daily_manage_times"
CB_ADM_DAILY_SET_CATEGORIES_MODE = f"{CB_ADM_}daily_set_cat_mode"
CB_ADM_DAILY_SET_CATEGORIES_MODE_OPT = f"{CB_ADM_}daily_set_cat_mode_opt"
CB_ADM_DAILY_SET_NUM_RANDOM_CATEGORIES = f"{CB_ADM_}daily_set_num_rand_cat"
CB_ADM_DAILY_MANAGE_SPECIFIC_CATEGORIES = f"{CB_ADM_}daily_manage_spec_cat"
CB_ADM_DAILY_SET_NUM_QUESTIONS = f"{CB_ADM_}daily_set_num_q"
CB_ADM_DAILY_SET_INTERVAL_SECONDS = f"{CB_ADM_}daily_set_interval"
CB_ADM_DAILY_SET_POLL_OPEN_SECONDS = f"{CB_ADM_}daily_set_poll_open"
CB_ADM_DAILY_TIME_ = f"{CB_ADM_}daily_time_"
CB_ADM_DAILY_TIME_ADD = f"{CB_ADM_DAILY_TIME_}add"
CB_ADM_DAILY_TIME_REMOVE = f"{CB_ADM_DAILY_TIME_}remove"
CB_ADM_DAILY_TIME_BACK_TO_LIST = f"{CB_ADM_DAILY_TIME_}back_to_times_list"
CB_ADM_DAILY_TIME_SET_TIMEZONE = f"{CB_ADM_DAILY_TIME_}set_timezone"

# ИЗМЕНЕНИЕ: Новые константы для управления автоудалением
CB_ADM_TOGGLE_AUTO_DELETE_BOT_MESSAGES = f"{CB_ADM_}toggle_auto_del_msg"
CB_ADM_TOGGLE_AUTO_DELETE_BOT_MESSAGES_OPT = f"{CB_ADM_}toggle_auto_del_msg_opt"

# ИЗМЕНЕНИЕ: Константа для настройки интервала обычных квизов
CB_ADM_SET_DEFAULT_INTERVAL_SECONDS = f"{CB_ADM_}set_default_interval"

# НОВОЕ: Константы для настройки пула категорий для /quiz
CB_ADM_QUIZ_SET_CATEGORIES_MODE = f"{CB_ADM_}quiz_set_cat_mode"
CB_ADM_QUIZ_SET_CATEGORIES_MODE_OPT = f"{CB_ADM_}quiz_set_cat_mode_opt"
CB_ADM_QUIZ_MANAGE_CATEGORIES_POOL = f"{CB_ADM_}quiz_manage_cat_pool"
CB_ADM_QUIZ_CAT_POOL_ = f"{CB_ADM_}quiz_cat_pool_"
CB_ADM_QUIZ_CAT_POOL_TOGGLE = f"{CB_ADM_QUIZ_CAT_POOL_}toggle"
CB_ADM_QUIZ_CAT_POOL_SAVE = f"{CB_ADM_QUIZ_CAT_POOL_}save"
CB_ADM_QUIZ_CAT_POOL_CLEAR = f"{CB_ADM_QUIZ_CAT_POOL_}clear"


CTX_ADMIN_CFG_CHAT_ID = 'admin_cfg_chat_id'
CTX_ADMIN_CFG_MSG_ID = 'admin_cfg_msg_id'
CTX_INPUT_TARGET_KEY_PATH = 'input_target_key_path'
CTX_INPUT_PROMPT = 'input_prompt_text'
CTX_INPUT_CONSTRAINTS = 'input_constraints_dict'
CTX_CURRENT_MENU_SENDER_CB_NAME = 'current_menu_sender_callback_name'
CTX_INPUT_CANCEL_CB_DATA = '_input_cancel_cb_data'
CTX_TEMP_CATEGORY_SELECTION = 'temp_category_selection_set'
CTX_CATEGORY_SELECTION_MODE = 'category_selection_mode_str'
CTX_CATEGORY_SELECTION_TITLE = 'category_selection_title_str'

# НОВОЕ: Константы для настройки пула категорий /quiz
CTX_QUIZ_CATEGORY_SELECTION_MODE = 'quiz_category_selection_mode_str'
CTX_QUIZ_TEMP_CATEGORY_SELECTION = 'quiz_temp_category_selection_set'

class ConfigHandlers:
    def __init__(self, app_config: AppConfig, data_manager: DataManager,
                 category_manager: CategoryManager, application: Application):
        self.app_config = app_config
        self.data_manager = data_manager
        self.category_manager = category_manager
        self.application = application
        self.daily_quiz_scheduler_ref: Optional[DailyQuizScheduler] = None
        self.wisdom_scheduler_ref: Optional[WisdomScheduler] = None
        # Semaphore to limit concurrent reschedule tasks and prevent CPU overload
        self._reschedule_semaphore = asyncio.Semaphore(3)  # Max 3 concurrent reschedule operations

    def set_daily_quiz_scheduler(self, scheduler: DailyQuizScheduler) -> None:
        self.daily_quiz_scheduler_ref = scheduler

    def set_wisdom_scheduler(self, scheduler: WisdomScheduler) -> None:
        self.wisdom_scheduler_ref = scheduler

    async def _safe_reschedule_job_for_chat(self, chat_id: int, timezone_change: bool = False, old_timezone: str = None, new_timezone: str = None) -> None:
        """
        Safely reschedule job for chat with concurrency control to prevent CPU overload.
        If timezone_change=True, attempts smart timezone adjustment instead of full reschedule.
        """
        if self.data_manager.postgres_storage:
            await self.data_manager.schedule_sync.tick()
            return
        if not self.daily_quiz_scheduler_ref:
            logger.warning(f"DailyQuizScheduler not available, skipping reschedule for chat {chat_id}")
            return

        async with self._reschedule_semaphore:
            try:
                if timezone_change and old_timezone and new_timezone and old_timezone != new_timezone:
                    # Пытаемся сделать умную коррекцию часового пояса
                    success = await self.daily_quiz_scheduler_ref.adjust_timezone_for_chat(chat_id, old_timezone, new_timezone)
                    if success:
                        logger.info(f"Successfully adjusted timezone for chat {chat_id} from {old_timezone} to {new_timezone}")
                        return
                    else:
                        logger.warning(f"Smart timezone adjustment failed for chat {chat_id}, falling back to full reschedule")

                # Полная перепланировка (fallback или обычная перепланировка)
                await self.daily_quiz_scheduler_ref.reschedule_job_for_chat(chat_id)
                logger.debug(f"Successfully rescheduled job for chat {chat_id}")

            except Exception as e:
                logger.error(f"Error rescheduling job for chat {chat_id}: {e}", exc_info=True)

    async def _is_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        return await is_user_admin_in_update(update, context)

    async def _update_config_message(self,
                                     query_or_update: Optional[Union[Update, CallbackQuery]],
                                     context: ContextTypes.DEFAULT_TYPE,
                                     new_text: str,
                                     new_markup: Optional[InlineKeyboardMarkup]):
        from modules.telegram_menu import card, acknowledge
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID)
        if not chat_id or query_or_update is None:
            return
        target = context.chat_data.get(CTX_ADMIN_CFG_MSG_ID)
        try:
            sent = await card(query_or_update, context, new_text, new_markup.inline_keyboard if new_markup else [],
                              parse_mode=ParseMode.MARKDOWN_V2, message_id=target)
            if sent:
                context.chat_data[CTX_ADMIN_CFG_MSG_ID] = sent.message_id
            if isinstance(query_or_update, CallbackQuery):
                await acknowledge(query_or_update)
        except Exception:
            logger.exception('Settings card update failed; no blind duplicate send')
            if isinstance(query_or_update, CallbackQuery):
                await acknowledge(query_or_update, 'Не удалось обновить меню. Попробуй ещё раз.', alert=True)

    async def admin_settings_entry(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        if not update.message or not update.effective_chat or not update.effective_user:
            return ConversationHandler.END
        
        import time
        start_time = time.time()
        logger.info(f"Команда /adminsettings получена в {start_time:.3f}")
        
        if not await self._is_admin(update, context):
            await update.message.reply_text(escape_markdown_v2("Эта команда доступна только администраторам чата."), parse_mode=ParseMode.MARKDOWN_V2)
            elapsed = time.time() - start_time
            logger.info(f"Команда /adminsettings завершена (не админ) за {elapsed:.3f}с")
            return ConversationHandler.END

        chat_id = update.effective_chat.id
        entry_message = context.chat_data.get('_menu_entry_message_id')
        context.chat_data.clear()
        context.chat_data[CTX_ADMIN_CFG_CHAT_ID] = chat_id
        if entry_message:
            context.chat_data[CTX_ADMIN_CFG_MSG_ID] = entry_message
        
        # Обновляем метаданные чата (название, тип) в фоновом режиме
        import asyncio
        asyncio.create_task(self.data_manager.update_chat_metadata(chat_id, context.bot))
        
        await self._send_main_cfg_menu(update, context)
        
        elapsed = time.time() - start_time
        logger.info(f"Команда /adminsettings обработана за {elapsed:.3f}с")
        return CFG_MAIN_MENU

    async def _send_main_cfg_menu(self, query_or_update: Optional[Union[Update, CallbackQuery]], context: ContextTypes.DEFAULT_TYPE):
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID)
        if not chat_id:
             logger.error("_send_main_cfg_menu: CTX_ADMIN_CFG_CHAT_ID не найден.")
             return
        
        # Read through to PG: changes from the local admin must appear immediately.
        settings = await self.data_manager.get_chat_settings_async(chat_id)
        defaults = self.app_config.default_chat_settings
        count = settings.get('default_num_questions', defaults.get('default_num_questions', 10))
        seconds = settings.get('default_open_period_seconds', defaults.get('default_open_period_seconds', 30))
        cleanup = settings.get('auto_delete_bot_messages', defaults.get('auto_delete_bot_messages', True))
        daily = settings.get('daily_quiz', {})
        wisdom = settings.get('daily_wisdom', {})
        label = 'Личные настройки' if chat_id > 0 else 'Настройки чата'
        text = f"*{escape_markdown_v2('⚙️ ' + label)}*\n\n"
        text += escape_markdown_v2(f"Классика: {count} вопросов · {seconds} секунд на ответ.\nИзменения сохраняются сразу — следующая игра использует их.")
        if context.bot_data.get('telegram_private_test'):
            text += '\n\n' + escape_markdown_v2('DEV: автоматические расписания здесь выключены. Можно настроить параметры для последующей проверки.')
        kb_buttons = [
            [InlineKeyboardButton(f"🎮 Квиз · {count} вопросов · {seconds} с", callback_data=CB_ADM_GOTO_QUIZ_MENU, style='primary')],
            [InlineKeyboardButton("📚 Разрешённые темы", callback_data=CB_ADM_MANAGE_ENABLED_CATEGORIES),
             InlineKeyboardButton("🚫 Исключённые", callback_data=CB_ADM_MANAGE_DISABLED_CATEGORIES)],
            [InlineKeyboardButton(f"🧹 Автоудаление: {'вкл' if cleanup else 'выкл'}", callback_data=CB_ADM_TOGGLE_AUTO_DELETE_BOT_MESSAGES)],
            [InlineKeyboardButton(f"📅 Квиз по расписанию · {'вкл' if daily.get('enabled') else 'выкл'}", callback_data=CB_ADM_GOTO_DAILY_MENU)],
            [InlineKeyboardButton(f"💡 Мудрость дня · {'вкл' if wisdom.get('enabled') else 'выкл'}", callback_data=CB_ADM_WISDOM_MENU)],
            [InlineKeyboardButton("Сбросить настройки…", callback_data=CB_ADM_CONFIRM_RESET_SETTINGS, style='danger')],
            [InlineKeyboardButton("‹ Главное меню", callback_data='nav:home'),
             InlineKeyboardButton("✓ Готово", callback_data=CB_ADM_FINISH_CONFIG)],
        ]
        context.chat_data[CTX_CURRENT_MENU_SENDER_CB_NAME] = "_send_main_cfg_menu"
        context.chat_data[CTX_INPUT_CANCEL_CB_DATA] = CB_ADM_BACK_TO_MAIN
        await self._update_config_message(query_or_update, context, text, InlineKeyboardMarkup(kb_buttons))

    def _format_settings_display(self, settings: Dict[str, Any], part: str = "main") -> str:
        lines = []
        def_chat_s = self.app_config.default_chat_settings

        time_setting_key_paths = [
            ["default_open_period_seconds"],
            ["default_announce_delay_seconds"],
            ["default_interval_seconds"],
            ["daily_quiz", "interval_seconds"],
            ["daily_quiz", "poll_open_seconds"]
        ]

        def get_and_format_value(setting_key_path: List[str], default_value_override: Any = None) -> str:
            current_value_in_settings = settings
            for key in setting_key_path:
                if isinstance(current_value_in_settings, dict):
                    current_value_in_settings = current_value_in_settings.get(key)
                else:
                    current_value_in_settings = None
                    break

            default_value_from_config_structure = def_chat_s
            for key in setting_key_path:
                if isinstance(default_value_from_config_structure, dict):
                    default_value_from_config_structure = default_value_from_config_structure.get(key)
                else:
                    default_value_from_config_structure = default_value_override
                    break
            
            # ИЗМЕНЕНИЕ: Убедимся, что default_value_from_config_structure не None перед использованием
            # Это особенно важно для новых настроек, которые могут отсутствовать в старых quiz_config.json
            if default_value_from_config_structure is None and default_value_override is not None:
                final_value_to_display = current_value_in_settings if current_value_in_settings is not None else default_value_override
            else:
                final_value_to_display = current_value_in_settings if current_value_in_settings is not None else default_value_from_config_structure


            if setting_key_path in time_setting_key_paths and isinstance(final_value_to_display, (int, float)):
                return escape_markdown_v2(format_seconds_to_human_readable_time(int(final_value_to_display)))

            if isinstance(final_value_to_display, list) and setting_key_path != ["daily_quiz", "times_msk"]:
                 if not final_value_to_display: return escape_markdown_v2("Нет")
                 return escape_markdown_v2(", ".join(sorted(str(item) for item in final_value_to_display)))

            if setting_key_path == ["daily_quiz", "times_msk"]:
                times_list_val = final_value_to_display
                if not isinstance(times_list_val, list) or not times_list_val:
                    return escape_markdown_v2("Не задано")
                formatted_times_str_list = []
                for t_entry in times_list_val:
                    if isinstance(t_entry, dict) and "hour" in t_entry and "minute" in t_entry:
                        try:
                           h, m = int(t_entry["hour"]), int(t_entry["minute"])
                           formatted_times_str_list.append(f"{h:02d}:{m:02d}")
                        except (ValueError, TypeError):
                           formatted_times_str_list.append("??:??")
                    else:
                        formatted_times_str_list.append("Некорр.запись")
                return escape_markdown_v2(", ".join(sorted(formatted_times_str_list))) + " MSK"

            if setting_key_path[-1] == "categories_mode":
                 mode_map = {"random": "🎲 Случайные", "specific": "🗂️ Выбранные", "all_enabled": "✅ Все разрешенные"}
                 return escape_markdown_v2(mode_map.get(str(final_value_to_display), "Неизвестно"))
            if setting_key_path[-1] == "quiz_categories_mode":
                 mode_map = {"all": "🌐 Все категории", "specific": "🗂️ Только выбранные", "exclude": "❌ Исключить выбранные"}
                 return escape_markdown_v2(mode_map.get(str(final_value_to_display), "Неизвестно"))
            if isinstance(final_value_to_display, bool):
                 return escape_markdown_v2("Вкл" if final_value_to_display else "Выкл")
            if setting_key_path == ["enabled_categories"] and final_value_to_display is None:
                return escape_markdown_v2("Все системные")
            return escape_markdown_v2(str(final_value_to_display)) if final_value_to_display is not None else escape_markdown_v2("Не задано")

        if part == "main" or part == "all":
            lines.append(f"*{escape_markdown_v2('Тип /quiz по умолчанию:')}* `{get_and_format_value(['default_quiz_type'])}`")
            lines.append(f"*{escape_markdown_v2('Кол-во вопросов /quiz:')}* `{get_and_format_value(['default_num_questions'])}`")
            lines.append(f"*{escape_markdown_v2('Кол-во категорий /quiz:')}* `{get_and_format_value(['num_categories_per_quiz'])}`")
            # Показываем пул категорий только если режим не "all"
            quiz_categories_mode = settings.get('quiz_categories_mode', 'all')
            lines.append(f"*{escape_markdown_v2('Режим пула категорий /quiz:')}* `{get_and_format_value(['quiz_categories_mode'])}`")
            
            if quiz_categories_mode != 'all':
                pool_value = get_and_format_value(['quiz_categories_pool'])
                if pool_value and pool_value != escape_markdown_v2("Нет"):
                    lines.append(f"*{escape_markdown_v2('Пул категорий /quiz:')}* `{pool_value}`")
            lines.append(f"*{escape_markdown_v2('Разрешенные категории для чата:')}* `{get_and_format_value(['enabled_categories'])}`")
            lines.append(f"*{escape_markdown_v2('Запрещенные категории для чата:')}* `{get_and_format_value(['disabled_categories'])}`")
            # ИЗМЕНЕНИЕ: Отображение новой настройки
            lines.append(f"*{escape_markdown_v2('Автоудаление сообщений бота:')}* `{get_and_format_value(['auto_delete_bot_messages'], default_value_override=True)}`")

        if part == "quiz" or part == "all":
            lines.append(f"*{escape_markdown_v2('Тип /quiz по умолчанию:')}* `{get_and_format_value(['default_quiz_type'])}`")
            lines.append(f"*{escape_markdown_v2('Кол-во вопросов:')}* `{get_and_format_value(['default_num_questions'])}`")
            lines.append(f"*{escape_markdown_v2('Кол-во категорий:')}* `{get_and_format_value(['num_categories_per_quiz'])}`")
            lines.append(f"*{escape_markdown_v2('Время ответа:')}* `{get_and_format_value(['default_open_period_seconds'])}` сек")
            lines.append(f"*{escape_markdown_v2('Интервал между вопросами:')}* `{get_and_format_value(['default_interval_seconds'])}`")
            lines.append(f"*{escape_markdown_v2('Анонс /quiz:')}* `{get_and_format_value(['default_announce_quiz'])}`")
            if settings.get('default_announce_quiz', def_chat_s.get('default_announce_quiz')):
                 lines.append(f"*{escape_markdown_v2('Задержка анонса:')}* `{get_and_format_value(['default_announce_delay_seconds'])}`")

        if part == "quiz_categories" or part == "all":
            lines.append(f"*{escape_markdown_v2('Режим выбора категорий:')}* `{get_and_format_value(['quiz_categories_mode'])}`")
            
            # Показываем пул категорий только если режим не "all"
            quiz_categories_mode = settings.get('quiz_categories_mode', 'all')
            if quiz_categories_mode != 'all':
                pool_value = get_and_format_value(['quiz_categories_pool'])
                if pool_value and pool_value != escape_markdown_v2("Нет"):
                    lines.append(f"*{escape_markdown_v2('Пул категорий:')}* `{pool_value}`")
                
            lines.append(f"*{escape_markdown_v2('Кол-во категорий для выбора:')}* `{get_and_format_value(['num_categories_per_quiz'])}`")

        if part == "daily_brief" or part == "daily" or part == "all":
            lines.append(f"*{escape_markdown_v2('Мудрость дня:')}* `{get_and_format_value(['daily_wisdom', 'enabled'])}`")
            lines.append(f"*{escape_markdown_v2('Ежедневная викторина:')}* `{get_and_format_value(['daily_quiz', 'enabled'])}`")
            daily_enabled_val = settings.get('daily_quiz', {}).get('enabled', def_chat_s.get('daily_quiz', {}).get('enabled',False))
            if daily_enabled_val or part == "daily":
                 lines.append(f"*{escape_markdown_v2('Время запуска:')}* `{get_and_format_value(['daily_quiz', 'times_msk'])}`")
                 lines.append(f"*{escape_markdown_v2('Категории ежедневной викторины:')}* `{get_and_format_value(['daily_quiz', 'categories_mode'])}`")
                 daily_cat_mode_val = settings.get('daily_quiz', {}).get('categories_mode', def_chat_s.get('daily_quiz', {}).get('categories_mode'))
                 if daily_cat_mode_val == 'random':
                      lines.append(f"*{escape_markdown_v2('Количество случайных категорий:')}* `{get_and_format_value(['daily_quiz', 'num_random_categories'])}`")
                 elif daily_cat_mode_val == 'specific':
                      lines.append(f"*{escape_markdown_v2('Выбранные категории:')}* `{get_and_format_value(['daily_quiz', 'specific_categories'])}`")
                 lines.append(f"*{escape_markdown_v2('Количество вопросов:')}* `{get_and_format_value(['daily_quiz', 'num_questions'])}`")
                 lines.append(f"*{escape_markdown_v2('Интервал между вопросами:')}* `{get_and_format_value(['daily_quiz', 'interval_seconds'])}`")
                 lines.append(f"*{escape_markdown_v2('Время на ответ:')}* `{get_and_format_value(['daily_quiz', 'poll_open_seconds'])}`")
        return "\n".join(lines)

    async def handle_main_menu_callbacks(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        query = update.callback_query
        await query.answer()
        action = query.data
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID)

        # Отладочный лог для меню выбора часового пояса
        if action.startswith("admcfg_wisdom_set_timezone:") or action == "admcfg_wisdom_menu":
            logger.info(f"DEBUG TIMEZONE: Получен колбек '{action}' для чата {chat_id}")
            logger.info(f"DEBUG TIMEZONE: Текущий контекст меню: {context.chat_data.get(CTX_CURRENT_MENU_SENDER_CB_NAME)}")

        if not chat_id: return ConversationHandler.END
        settings = await self.data_manager.get_chat_settings_async(chat_id)
        def_s = self.app_config.default_chat_settings
        context.chat_data[CTX_CURRENT_MENU_SENDER_CB_NAME] = "_send_main_cfg_menu"
        context.chat_data[CTX_INPUT_CANCEL_CB_DATA] = CB_ADM_BACK_TO_MAIN

        if action == CB_ADM_FINISH_CONFIG:
            # Удаляем меню настроек
            target_msg_id = context.chat_data.get(CTX_ADMIN_CFG_MSG_ID)
            if target_msg_id:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=target_msg_id)
                except Exception as e:
                    logger.debug(f"Не удалось удалить сообщение меню: {e}")
            
            # Отправляем финальное сообщение
            await safe_send_message(
                context.bot,
                chat_id,
                escape_markdown_v2("✅ Настройки сохранены и применены!"),
                parse_mode=ParseMode.MARKDOWN_V2
            )
            
            # Отвечаем на callback query
            try:
                await query.answer("Настройки сохранены")
            except Exception:
                pass
            
            context.chat_data.clear()
            return ConversationHandler.END
        elif action == CB_ADM_BACK_TO_MAIN:
            await self._send_main_cfg_menu(query, context)
            return CFG_MAIN_MENU
        elif action == CB_ADM_WISDOM_MENU and context.chat_data.get(CTX_CURRENT_MENU_SENDER_CB_NAME) == "_send_timezone_selection_menu":
            logger.info(f"DEBUG TIMEZONE: Обрабатываем кнопку 'Назад' из меню выбора часового пояса: {action}")
            await self._send_wisdom_menu(query, context)
            return CFG_WISDOM_MENU
        elif action == CB_ADM_WISDOM_MENU:
            logger.info(f"DEBUG TIMEZONE: Обрабатываем кнопку 'Назад' из основного меню: {action}")
            await self._send_wisdom_menu(query, context)
            return CFG_WISDOM_MENU
        elif action == CB_ADM_WISDOM_TOGGLE:
            wisdom_settings = settings.get('daily_wisdom', {})
            current_enabled = wisdom_settings.get('enabled', False)
            new_enabled = not current_enabled

            # Обновляем настройки
            if 'daily_wisdom' not in settings:
                settings['daily_wisdom'] = {'enabled': False, 'time': '09:00', 'timezone': 'Europe/Moscow'}
            settings['daily_wisdom']['enabled'] = new_enabled
            await self.data_manager.update_chat_setting(chat_id, ["daily_wisdom", "enabled"], new_enabled)

            # Управляем планировщиком
            if self.data_manager.postgres_storage:
                await self._safe_reschedule_job_for_chat(chat_id)
            elif self.wisdom_scheduler_ref:
                if new_enabled:
                    wisdom_time = settings['daily_wisdom'].get('time', '09:00')
                    # Используем часовой пояс от ежедневной викторины
                    wisdom_timezone = settings.get('daily_quiz', {}).get('timezone', 'Europe/Moscow')
                    self.wisdom_scheduler_ref.schedule_wisdom_for_chat(chat_id, wisdom_time, wisdom_timezone)
                else:
                    self.wisdom_scheduler_ref.unschedule_wisdom_for_chat(chat_id)

            await self._send_wisdom_menu(query, context)
            return CFG_WISDOM_MENU
        elif action == CB_ADM_WISDOM_SET_TIME:
            context.chat_data[CTX_INPUT_PROMPT] = escape_markdown_v2("Введите время отправки мудрости в формате ЧЧ:ММ (например, 09:00 или 14:30):")
            context.chat_data[CTX_INPUT_TARGET_KEY_PATH] = ["daily_wisdom", "time"]
            context.chat_data[CTX_INPUT_CONSTRAINTS] = {"type": "time"}
            await self._update_config_message(query, context, context.chat_data[CTX_INPUT_PROMPT], InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Отмена", callback_data=CB_ADM_WISDOM_MENU)]]))
            return CFG_WISDOM_TIME_INPUT
        elif action == CB_ADM_WISDOM_SET_TIMEZONE:
            await self._send_timezone_selection_menu(query, context)
            return CFG_WISDOM_TIMEZONE_MENU
        elif action == CB_ADM_WISDOM_MENU:
            # Обработка отмены из состояния ввода времени или перехода к меню мудрости
            await self._send_wisdom_menu(query, context)
            return CFG_WISDOM_MENU
        elif action == CB_ADM_WISDOM_BACK_TO_MAIN:
            await self._send_main_cfg_menu(query, context)
            return CFG_MAIN_MENU

        elif action.startswith(f"{CB_ADM_WISDOM_SET_TIMEZONE}:"):
            # Обработка выбора часового пояса для мудрости дня
            logger.info(f"DEBUG TIMEZONE: Обрабатываем выбор часового пояса: {action}")
            selected_timezone = action.split(":", 1)[1]

            settings = await self.data_manager.get_chat_settings_async(chat_id)
            if 'daily_wisdom' not in settings:
                settings['daily_wisdom'] = {'enabled': False, 'time': '09:00', 'timezone': 'Europe/Moscow'}

            # У квиза и мудрости общий часовой пояс чата.
            old_timezone = settings.get('daily_quiz', {}).get('timezone', 'Europe/Moscow')
            # Используем часовой пояс от ежедневной викторины
            actual_timezone = selected_timezone
            await self.data_manager.update_chat_setting(chat_id, ["daily_quiz", "timezone"], selected_timezone)

            # Перепланируем если мудрость включена
            if self.data_manager.postgres_storage:
                await self._safe_reschedule_job_for_chat(chat_id)
            else:
                await self._safe_reschedule_job_for_chat(chat_id)
                if self.wisdom_scheduler_ref and settings['daily_wisdom'].get('enabled', False):
                    wisdom_time = settings['daily_wisdom'].get('time', '09:00')
                    self.wisdom_scheduler_ref.schedule_wisdom_for_chat(chat_id, wisdom_time, actual_timezone)

            logger.info(f"Часовой пояс мудрости дня для чата {chat_id} изменен: {old_timezone} → {selected_timezone}")
            await query.answer(f"Часовой пояс изменён на {selected_timezone}", show_alert=True)
            await self._send_wisdom_menu(query, context)
            return CFG_WISDOM_MENU
        elif action == CB_ADM_SET_DEFAULT_QUIZ_TYPE:
            current_val = settings.get('default_quiz_type', def_s['default_quiz_type'])
            kb = []
            for q_type_key in ["session", "single"]:
                q_type_config = self.app_config.quiz_types_config.get(q_type_key, {})
                q_type_name = q_type_config.get("type", q_type_key)
                prefix = "✅ " if q_type_name == current_val else "☑️ "
                kb.append([InlineKeyboardButton(f"{prefix}{q_type_name.capitalize()}", callback_data=f"{CB_ADM_SET_DEFAULT_QUIZ_TYPE_OPT}:{q_type_name}")])
            kb.append([InlineKeyboardButton("⬅️ Назад", callback_data=CB_ADM_BACK_TO_MAIN)])
            await self._update_config_message(query, context, escape_markdown_v2("Выберите тип /quiz по умолчанию:"), InlineKeyboardMarkup(kb))
            return CFG_MAIN_MENU
        elif action.startswith(CB_ADM_SET_DEFAULT_QUIZ_TYPE_OPT):
            val = action.split(":", 1)[1]
            await self.data_manager.update_chat_setting(chat_id, ["default_quiz_type"], val)
            # Очищаем кэш настроек для быстрой работы
            self._clear_settings_cache(context, chat_id)
            await self._send_main_cfg_menu(query, context)
            return CFG_MAIN_MENU
        elif action == CB_ADM_SET_DEFAULT_ANNOUNCE_QUIZ:
            current_val = settings.get('default_announce_quiz', def_s['default_announce_quiz'])
            kb = [
                [InlineKeyboardButton(f"{'✅ ' if current_val else '☑️ '}Включить анонс", callback_data=f"{CB_ADM_SET_DEFAULT_ANNOUNCE_QUIZ_OPT}:true")],
                [InlineKeyboardButton(f"{'✅ ' if not current_val else '☑️ '}Выключить анонс", callback_data=f"{CB_ADM_SET_DEFAULT_ANNOUNCE_QUIZ_OPT}:false")],
                [InlineKeyboardButton("⬅️ Назад", callback_data=CB_ADM_BACK_TO_MAIN)]
            ]
            await self._update_config_message(query, context, escape_markdown_v2("Включить анонс для /quiz по умолчанию?"), InlineKeyboardMarkup(kb))
            return CFG_MAIN_MENU
        elif action.startswith(CB_ADM_SET_DEFAULT_ANNOUNCE_QUIZ_OPT):
            val = action.split(":", 1)[1] == "true"
            await self.data_manager.update_chat_setting(chat_id, ["default_announce_quiz"], val)
            await self._send_main_cfg_menu(query, context)
            return CFG_MAIN_MENU
        # ИЗМЕНЕНИЕ: Добавлен обработчик для новой кнопки
        elif action == CB_ADM_TOGGLE_AUTO_DELETE_BOT_MESSAGES:
            current_val = settings.get('auto_delete_bot_messages', def_s.get('auto_delete_bot_messages', True))
            kb = [
                [InlineKeyboardButton(f"{'✅ ' if current_val else '☑️ '}Включить автоудаление", callback_data=f"{CB_ADM_TOGGLE_AUTO_DELETE_BOT_MESSAGES_OPT}:true")],
                [InlineKeyboardButton(f"{'✅ ' if not current_val else '☑️ '}Выключить автоудаление", callback_data=f"{CB_ADM_TOGGLE_AUTO_DELETE_BOT_MESSAGES_OPT}:false")],
                [InlineKeyboardButton("⬅️ Назад", callback_data=CB_ADM_BACK_TO_MAIN)]
            ]
            prompt_text_escaped = escape_markdown_v2("Включить автоматическое удаление сообщений бота (опросы, пояснения, анонсы и т.д.) после их завершения/истечения времени?")
            await self._update_config_message(query, context, prompt_text_escaped, InlineKeyboardMarkup(kb))
            return CFG_MAIN_MENU
        elif action.startswith(CB_ADM_TOGGLE_AUTO_DELETE_BOT_MESSAGES_OPT):
            val_str = action.split(":", 1)[1]
            new_value = val_str == "true"
            await self.data_manager.update_chat_setting(chat_id, ["auto_delete_bot_messages"], new_value)
            await self._send_main_cfg_menu(query, context)
            return CFG_MAIN_MENU
        elif action == CB_ADM_GOTO_QUIZ_MENU:
            await self._send_quiz_cfg_menu(query, context)
            return CFG_QUIZ_MENU
        elif action == CB_ADM_GOTO_QUIZ_CATEGORIES_MENU:
            await self._send_quiz_categories_cfg_menu(query, context)
            return CFG_QUIZ_CATEGORIES_MENU
        elif action == CB_ADM_GOTO_DAILY_MENU:
            await self._send_daily_cfg_menu(query, context)
            return CFG_DAILY_MENU
        elif action == CB_ADM_MANAGE_ENABLED_CATEGORIES:
            context.chat_data[CTX_CATEGORY_SELECTION_MODE] = 'enabled_categories'
            context.chat_data[CTX_CATEGORY_SELECTION_TITLE] = escape_markdown_v2('разрешенных категорий для /quiz')
            current_selection = settings.get('enabled_categories')
            context.chat_data[CTX_TEMP_CATEGORY_SELECTION] = set(current_selection) if isinstance(current_selection, list) else (None if current_selection is None else set())
            await self._send_category_selection_menu(query, context)
            return CFG_SELECT_GENERAL_CATEGORIES
        elif action == CB_ADM_MANAGE_DISABLED_CATEGORIES:
            context.chat_data[CTX_CATEGORY_SELECTION_MODE] = 'disabled_categories'
            context.chat_data[CTX_CATEGORY_SELECTION_TITLE] = escape_markdown_v2('запрещенных категорий (для этого чата)')
            context.chat_data[CTX_TEMP_CATEGORY_SELECTION] = set(settings.get('disabled_categories', []))
            await self._send_category_selection_menu(query, context)
            return CFG_SELECT_GENERAL_CATEGORIES
        elif action == CB_ADM_CONFIRM_RESET_SETTINGS:
            kb = [[InlineKeyboardButton("‼️ ДА, СБРОСИТЬ ВСЕ НАСТРОЙКИ ‼️", callback_data=CB_ADM_EXECUTE_RESET_SETTINGS)],
                  [InlineKeyboardButton("⬅️ Нет, отмена", callback_data=CB_ADM_BACK_TO_MAIN)]]
            reset_confirm_text = escape_markdown_v2("Вы уверены, что хотите сбросить ВСЕ настройки этого чата к значениям по умолчанию?")
            await self._update_config_message(query, context, reset_confirm_text, InlineKeyboardMarkup(kb))
            return CFG_CONFIRM_RESET
        return CFG_MAIN_MENU

    def _clear_settings_cache(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
        """Очищает кэш настроек для быстрой работы"""
        cache_key = f"cfg_menu_{chat_id}"
        if cache_key in context.chat_data:
            del context.chat_data[cache_key]
            logger.debug(f"Кэш настроек очищен для чата {chat_id}")

    async def handle_input_value(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        cancel_cb_data_for_current_input = context.chat_data.get(CTX_INPUT_CANCEL_CB_DATA, CB_ADM_BACK_TO_MAIN)

        if not update.message or not update.message.text:
            prompt_text = context.chat_data.get(CTX_INPUT_PROMPT, escape_markdown_v2("Пожалуйста, введите корректное значение текстом или отмените."))
            await self._update_config_message(update, context, prompt_text, InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Отмена", callback_data=cancel_cb_data_for_current_input)]]))
            return CFG_INPUT_VALUE

        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID)
        if not chat_id:
            return ConversationHandler.END

        user_id = update.message.from_user.id if update.message.from_user else "Unknown"
        raw_value = update.message.text.strip()
        
        key_path: Optional[List[str]] = context.chat_data.get(CTX_INPUT_TARGET_KEY_PATH)
        constraints: Optional[Dict[str, Any]] = context.chat_data.get(CTX_INPUT_CONSTRAINTS)

        # Логируем все вводы значений на уровне DEBUG
        # Логируем ввод только для важных полей или при ошибках
        if key_path == ["daily_quiz", "times_msk"]:
            logger.debug(f"Админ {user_id} ввел время для чата {chat_id}: '{raw_value}'")
        else:
            logger.debug(f"📝 Ввод значения: '{raw_value}' | Пользователь: {user_id} | Чат: {chat_id}")
        menu_sender_method_name = context.chat_data.get(CTX_CURRENT_MENU_SENDER_CB_NAME, "_send_main_cfg_menu")
        fallback_menu_sender_method = getattr(self, menu_sender_method_name, self._send_main_cfg_menu)

        fallback_state_after_input: str
        if menu_sender_method_name == "_send_daily_cfg_menu": fallback_state_after_input = CFG_DAILY_MENU
        elif menu_sender_method_name == "_send_daily_times_menu": fallback_state_after_input = CFG_DAILY_TIMES_MENU
        elif menu_sender_method_name == "_send_quiz_cfg_menu": fallback_state_after_input = CFG_QUIZ_MENU
        elif menu_sender_method_name == "_send_wisdom_menu": fallback_state_after_input = CFG_WISDOM_MENU
        else: fallback_state_after_input = CFG_MAIN_MENU

        if not chat_id or not key_path or not constraints:
            await update.message.reply_text(escape_markdown_v2("Ошибка сессии настроек. Пожалуйста, начните заново."), parse_mode=ParseMode.MARKDOWN_V2)
            context.chat_data.clear()
            return ConversationHandler.END

        raw_value = update.message.text.strip()
        parsed_value: Any = None
        error_msg_unescaped: Optional[str] = None
        val_type = constraints.get('type', 'int')

        if val_type == 'int':
            try:
                val = int(raw_value)
                min_val, max_val = constraints.get('min'), constraints.get('max')
                if (min_val is not None and val < min_val) or \
                   (max_val is not None and val > max_val):
                    unit_for_error = "сек" if key_path in [["default_open_period_seconds"], ["default_announce_delay_seconds"], ["daily_quiz", "interval_seconds"], ["daily_quiz", "poll_open_seconds"]] else ""
                    error_msg_unescaped = f"Значение должно быть в диапазоне от {min_val} до {max_val} {unit_for_error.strip()}."
                else: parsed_value = val
            except ValueError: error_msg_unescaped = "Некорректное число. Пожалуйста, введите целое число."
        elif val_type == 'time':
            if constraints.get('action') == 'add_to_list':
                try:
                    h_str, m_str = raw_value.split(':')
                    h, m = int(h_str), int(m_str)
                    if not (0 <= h <= 23 and 0 <= m <= 59):
                        error_msg_unescaped = "Некорректное время. Часы 0-23, минуты 0-59."
                    else:
                        chat_settings_current = await self.data_manager.get_chat_settings_async(chat_id)
                        daily_settings_current = chat_settings_current.setdefault("daily_quiz", {})
                        times_list_current: List[Dict[str,int]] = daily_settings_current.setdefault("times_msk", [])
                        new_time_entry = {"hour": h, "minute": m}

                        max_times = self.app_config.max_daily_quiz_times_per_chat
                        if len(times_list_current) >= max_times:
                            error_msg_unescaped = f"Достигнут лимит в {max_times} {pluralize(max_times, 'настройку', 'настройки', 'настроек')} времени."
                        elif new_time_entry in times_list_current:
                            error_msg_unescaped = "Такое время уже существует в списке."
                        else:
                            times_list_current.append(new_time_entry)
                            times_list_current.sort(key=lambda t: (t.get("hour",0), t.get("minute",0)))
                            # Save the complete list once via the common commit
                            # below; never replace times_msk with a display string.
                            parsed_value = times_list_current
                except ValueError: error_msg_unescaped = "Неверный формат времени. Ожидается ЧЧ:ММ (например, 07:30)."
                except Exception as e_time_parse:
                    logger.error(f"Непредвиденная ошибка парсинга времени '{raw_value}': {e_time_parse}")
                    error_msg_unescaped = "Произошла ошибка при обработке введенного времени."
            elif key_path == ["daily_wisdom", "time"]:
                # Обработка времени мудрости дня
                try:
                    h_str, m_str = raw_value.split(':')
                    h, m = int(h_str), int(m_str)
                    if not (0 <= h <= 23 and 0 <= m <= 59):
                        error_msg_unescaped = "Некорректное время. Часы 0-23, минуты 0-59."
                    else:
                        # Устанавливаем parsed_value для общего механизма сохранения
                        parsed_value = f"{h:02d}:{m:02d}"

                        # Перепланируем если мудрость включена
                        settings = await self.data_manager.get_chat_settings_async(chat_id)
                        if not self.data_manager.postgres_storage and self.wisdom_scheduler_ref and settings.get('daily_wisdom', {}).get('enabled', False):
                            # Используем часовой пояс от ежедневной викторины
                            timezone_str = settings.get('daily_quiz', {}).get('timezone', 'Europe/Moscow')
                            self.wisdom_scheduler_ref.schedule_wisdom_for_chat(str(chat_id), raw_value, timezone_str)

                        logger.info(f"Мудрость дня для чата {chat_id} установлена на {raw_value}")
                except ValueError: error_msg_unescaped = "Неверный формат времени. Ожидается ЧЧ:ММ (например, 09:00)."
                except Exception as e_time_parse:
                    logger.error(f"Непредвиденная ошибка парсинга времени '{raw_value}': {e_time_parse}")
                    error_msg_unescaped = "Произошла ошибка при обработке введенного времени."
            else: error_msg_unescaped = "Неизвестное действие для типа 'time'."

        try: await update.message.delete()
        except Exception as e_del_input: logger.debug(f"Не удалось удалить сообщение с вводом: {e_del_input}")

        if error_msg_unescaped:
            original_prompt_text = context.chat_data.get(CTX_INPUT_PROMPT, escape_markdown_v2("Пожалуйста, введите корректное значение."))
            error_plus_prompt_text = f"{escape_markdown_v2(error_msg_unescaped)}\n\n{original_prompt_text}"
            await self._update_config_message(update, context, error_plus_prompt_text, InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Отмена", callback_data=cancel_cb_data_for_current_input)]]))
            return CFG_INPUT_VALUE

        if parsed_value is not None:
            await self.data_manager.update_chat_setting(chat_id, key_path, parsed_value)

        if self.data_manager.postgres_storage and key_path and key_path[0] in {"daily_quiz", "daily_wisdom"}:
            await self._safe_reschedule_job_for_chat(chat_id)
        elif key_path and key_path[0].startswith("daily_quiz") and self.daily_quiz_scheduler_ref:
            asyncio.create_task(self._safe_reschedule_job_for_chat(chat_id))

        await fallback_menu_sender_method(update, context)
        return fallback_state_after_input

    async def _send_category_selection_menu(self, query: Optional[CallbackQuery], context: ContextTypes.DEFAULT_TYPE):
        selection_mode: str = context.chat_data.get(CTX_CATEGORY_SELECTION_MODE, 'unknown')
        title_part_md_escaped: str = context.chat_data.get(CTX_CATEGORY_SELECTION_TITLE, escape_markdown_v2('категорий'))
        temp_selection: Optional[Set[str]] = context.chat_data.get(CTX_TEMP_CATEGORY_SELECTION)
        category_id_map: Dict[str, str] = {}
        context.chat_data['_category_id_map'] = category_id_map
        all_sys_categories_names = sorted(self.category_manager.get_all_category_names())

        back_cb_target = CB_ADM_BACK_TO_MAIN
        if selection_mode == 'daily_specific_categories':
            back_cb_target = CB_ADM_BACK_TO_DAILY_MENU
        context.chat_data[CTX_INPUT_CANCEL_CB_DATA] = back_cb_target

        if not all_sys_categories_names:
             no_cats_text = escape_markdown_v2(f"Нет доступных категорий для выбора {title_part_md_escaped}.")
             await self._update_config_message(query, context, no_cats_text, InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=back_cb_target)]]))
             return
        kb = []
        text_lines = [f"*{escape_markdown_v2('Выбор')} {title_part_md_escaped}:*"]
        if selection_mode == 'enabled_categories':
            text_lines.append(escape_markdown_v2("Если ни одна категория не выбрана, то для /quiz будут разрешены все системные категории (кроме глобально 'Запрещенных')."))
            is_all_enabled_mode = temp_selection is None
            prefix_for_all_mode = "✅ " if is_all_enabled_mode else "☑️ "
            kb.append([InlineKeyboardButton(f"{prefix_for_all_mode}Разрешить все системные категории", callback_data=f"{CB_ADM_CAT_CLEAR_SELECTION}:all_mode")])

        for i, cat_name_unescaped in enumerate(all_sys_categories_names):
            short_cat_id = f"c{i}"
            category_id_map[short_cat_id] = cat_name_unescaped
            is_selected_flag = temp_selection is not None and cat_name_unescaped in temp_selection
            prefix_for_category = "✅ " if is_selected_flag else "☑️ "
            button_text = cat_name_unescaped
            if len(button_text) > 30: button_text = button_text[:27] + "..."
            kb.append([InlineKeyboardButton(f"{prefix_for_category}{button_text}", callback_data=f"{CB_ADM_CAT_TOGGLE}:{short_cat_id}")])

        kb.append([InlineKeyboardButton("💾 Сохранить", callback_data=CB_ADM_CAT_SAVE_SELECTION),
                   InlineKeyboardButton("⬅️ Назад", callback_data=back_cb_target)])
        if selection_mode != 'enabled_categories' or (selection_mode == 'enabled_categories' and temp_selection is not None):
             kb.append([InlineKeyboardButton("🧹 Сбросить текущий выбор", callback_data=f"{CB_ADM_CAT_CLEAR_SELECTION}:clear_list")])
        final_text_for_menu = "\n".join(text_lines)
        await self._update_config_message(query, context, final_text_for_menu, InlineKeyboardMarkup(kb))

    async def handle_category_selection_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        query = update.callback_query
        await query.answer()
        action = query.data
        user_id = query.from_user.id if query.from_user else "Unknown"
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID) or "Unknown"
        
        # Логируем все нажатия кнопок на уровне DEBUG
        logger.debug(f"🔘 Админ выбор категорий: {action} | Пользователь: {user_id} | Чат: {chat_id}")
        
        if not action: return CFG_SELECT_GENERAL_CATEGORIES
        if not chat_id: return ConversationHandler.END
        selection_mode: Optional[str] = context.chat_data.get(CTX_CATEGORY_SELECTION_MODE)
        temp_selection: Optional[Set[str]] = context.chat_data.get(CTX_TEMP_CATEGORY_SELECTION)
        category_id_map: Optional[Dict[str, str]] = context.chat_data.get('_category_id_map')

        if not chat_id or not selection_mode or (not category_id_map and action.startswith(CB_ADM_CAT_TOGGLE)):
            await query.message.reply_text(escape_markdown_v2("Ошибка сессии выбора категорий. Пожалуйста, начните настройку заново."), parse_mode=ParseMode.MARKDOWN_V2)
            context.chat_data.clear()
            return ConversationHandler.END

        if action.startswith(CB_ADM_CAT_TOGGLE):
            short_cat_id_from_cb = action.split(":", 1)[1]
            cat_name_to_toggle = category_id_map.get(short_cat_id_from_cb) if category_id_map else None
            if not cat_name_to_toggle: return CFG_SELECT_GENERAL_CATEGORIES

            if selection_mode == 'enabled_categories':
                if temp_selection is None:
                    temp_selection = {cat_name_to_toggle}
                elif cat_name_to_toggle in temp_selection:
                    temp_selection.remove(cat_name_to_toggle)
                    if not temp_selection: temp_selection = None
                else: temp_selection.add(cat_name_to_toggle)
            else: 
                if temp_selection is None: temp_selection = set() 
                if cat_name_to_toggle in temp_selection: temp_selection.remove(cat_name_to_toggle)
                else: temp_selection.add(cat_name_to_toggle)
            context.chat_data[CTX_TEMP_CATEGORY_SELECTION] = temp_selection
            await self._send_category_selection_menu(query, context)
            return CFG_SELECT_GENERAL_CATEGORIES
        elif action.startswith(CB_ADM_CAT_CLEAR_SELECTION):
            clear_action_type = action.split(":",1)[1]
            if selection_mode == 'enabled_categories' and clear_action_type == 'all_mode':
                context.chat_data[CTX_TEMP_CATEGORY_SELECTION] = None
            elif clear_action_type == 'clear_list': 
                context.chat_data[CTX_TEMP_CATEGORY_SELECTION] = set()
            await self._send_category_selection_menu(query, context)
            return CFG_SELECT_GENERAL_CATEGORIES
        elif action == CB_ADM_CAT_SAVE_SELECTION:
            final_selection_to_save_in_db: Optional[List[str]]
            if temp_selection is None and selection_mode == 'enabled_categories':
                final_selection_to_save_in_db = None
            else: 
                final_selection_to_save_in_db = sorted(list(temp_selection)) if temp_selection is not None else []

            key_path_map_for_saving = {
                'enabled_categories': ["enabled_categories"],
                'disabled_categories': ["disabled_categories"],
                'daily_specific_categories': ["daily_quiz", "specific_categories"]
            }
            key_path_to_save_in_db = key_path_map_for_saving.get(selection_mode)
            if not key_path_to_save_in_db: return CFG_SELECT_GENERAL_CATEGORIES

            await self.data_manager.update_chat_setting(chat_id, key_path_to_save_in_db, final_selection_to_save_in_db)
            if selection_mode == 'daily_specific_categories' and self.daily_quiz_scheduler_ref:
                 asyncio.create_task(self._safe_reschedule_job_for_chat(chat_id))

            if selection_mode == 'daily_specific_categories':
                await self._send_daily_cfg_menu(query, context)
                return CFG_DAILY_MENU
            else:
                await self._send_main_cfg_menu(query, context)
                return CFG_MAIN_MENU
        return CFG_SELECT_GENERAL_CATEGORIES

    async def _send_daily_cfg_menu(self, query_or_update: Optional[Union[Update, CallbackQuery]], context: ContextTypes.DEFAULT_TYPE):
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID)
        if not chat_id: return

        settings = await self.data_manager.get_chat_settings_async(chat_id)
        display_text = self._format_settings_display(settings, part="daily")
        header_text = f"*{escape_markdown_v2('📅 Настройки Ежедневной Викторины')}*"
        prompt_text = escape_markdown_v2("Выберите параметр для изменения:")
        text_for_menu = f"{header_text}\n\n{display_text}\n\n{prompt_text}"

        daily_s_chat_current = settings.get("daily_quiz", {})
        def_daily_s_from_appconfig = self.app_config.daily_quiz_defaults
        is_daily_enabled_currently = daily_s_chat_current.get("enabled", def_daily_s_from_appconfig.get("enabled", False))

        kb = [[InlineKeyboardButton(f"{'Выключить' if is_daily_enabled_currently else 'Включить'} ежедневную викторину",
                                   callback_data=f"{CB_ADM_DAILY_TOGGLE_ENABLED}:{str(not is_daily_enabled_currently).lower()}")]]
        if is_daily_enabled_currently:
            kb.extend([
                [InlineKeyboardButton("⏰ Управление временами запуска", callback_data=CB_ADM_DAILY_MANAGE_TIMES)],
                [InlineKeyboardButton("Режим выбора категорий", callback_data=CB_ADM_DAILY_SET_CATEGORIES_MODE)],
                [InlineKeyboardButton("Кол-во вопросов", callback_data=CB_ADM_DAILY_SET_NUM_QUESTIONS)],
                [InlineKeyboardButton("Интервал между вопросами", callback_data=CB_ADM_DAILY_SET_INTERVAL_SECONDS)], 
                [InlineKeyboardButton("Время на ответ", callback_data=CB_ADM_DAILY_SET_POLL_OPEN_SECONDS)],      
            ])
        kb.append([InlineKeyboardButton("⬅️ Назад в главное меню", callback_data=CB_ADM_BACK_TO_MAIN)])

        context.chat_data[CTX_CURRENT_MENU_SENDER_CB_NAME] = "_send_daily_cfg_menu"
        context.chat_data[CTX_INPUT_CANCEL_CB_DATA] = CB_ADM_BACK_TO_DAILY_MENU
        await self._update_config_message(query_or_update, context, text_for_menu, InlineKeyboardMarkup(kb))

    async def _send_quiz_cfg_menu(self, query_or_update: Optional[Union[Update, CallbackQuery]], context: ContextTypes.DEFAULT_TYPE):
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID)
        if not chat_id: return

        settings = await self.data_manager.get_chat_settings_async(chat_id)
        display_text = self._format_settings_display(settings, part="quiz")
        header_text = f"*{escape_markdown_v2('🏁 Настройки /quiz')}*"
        prompt_text = escape_markdown_v2("Выберите параметр для изменения:")
        text_for_menu = f"{header_text}\n\n{display_text}\n\n{prompt_text}"

        kb = [
            [InlineKeyboardButton("Тип /quiz", callback_data=CB_ADM_SET_DEFAULT_QUIZ_TYPE),
             InlineKeyboardButton("Кол-во вопросов", callback_data=CB_ADM_SET_DEFAULT_NUM_QUESTIONS)],
            [InlineKeyboardButton("Кол-во категорий", callback_data=CB_ADM_SET_DEFAULT_NUM_CATEGORIES)],
            [InlineKeyboardButton("Время ответа", callback_data=CB_ADM_SET_DEFAULT_OPEN_PERIOD)],
            [InlineKeyboardButton("Интервал между вопросами", callback_data=CB_ADM_SET_DEFAULT_INTERVAL_SECONDS)],
            [InlineKeyboardButton("Анонс /quiz", callback_data=CB_ADM_SET_DEFAULT_ANNOUNCE_QUIZ),
             InlineKeyboardButton("Задержка анонса", callback_data=CB_ADM_SET_DEFAULT_ANNOUNCE_DELAY)],
            [InlineKeyboardButton("🗂️ Настройки категорий", callback_data=CB_ADM_QUIZ_SET_CATEGORIES_MODE)],
            [InlineKeyboardButton("⬅️ Назад в главное меню", callback_data=CB_ADM_BACK_TO_MAIN)]
        ]

        context.chat_data[CTX_CURRENT_MENU_SENDER_CB_NAME] = "_send_quiz_cfg_menu"
        context.chat_data[CTX_INPUT_CANCEL_CB_DATA] = CB_ADM_BACK_TO_QUIZ_MENU
        await self._update_config_message(query_or_update, context, text_for_menu, InlineKeyboardMarkup(kb))

    async def _send_wisdom_menu(self, query_or_update: Optional[Union[Update, CallbackQuery]], context: ContextTypes.DEFAULT_TYPE):
        """Отправляет меню настройки мудрости дня"""
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID)
        if not chat_id: return

        settings = await self.data_manager.get_chat_settings_async(chat_id)
        wisdom_settings = settings.get('daily_wisdom', {})

        # Форматируем текущие настройки
        enabled = wisdom_settings.get('enabled', False)
        time_str = wisdom_settings.get('time', '09:00')

        status_emoji = "✅" if enabled else "❌"
        header_text = f"*{escape_markdown_v2('🧠 Настройки мудрости дня')}*"
        status_text = f"{status_emoji} *Статус:* {'Включено' if enabled else 'Выключено'}"
        time_text = f"⏰ *Время отправки:* `{escape_markdown_v2(time_str)}`"
        timezone_note = f"🌍 *Часовой пояс:* Используется тот же, что и для ежедневной викторины"

        text = f"{header_text}\n\n{status_text}\n{time_text}\n{timezone_note}\n\n{escape_markdown_v2('Выберите действие:')}"

        kb = [
            [InlineKeyboardButton(f"{'❌ Выключить' if enabled else '✅ Включить'} мудрость дня", callback_data=CB_ADM_WISDOM_TOGGLE)],
            [InlineKeyboardButton(f"⏰ Изменить время ({time_str})", callback_data=CB_ADM_WISDOM_SET_TIME)],
            [InlineKeyboardButton("⬅️ Назад в главное меню", callback_data=CB_ADM_WISDOM_BACK_TO_MAIN)]
        ]

        context.chat_data[CTX_CURRENT_MENU_SENDER_CB_NAME] = "_send_wisdom_menu"
        context.chat_data[CTX_INPUT_CANCEL_CB_DATA] = CB_ADM_WISDOM_BACK_TO_MAIN
        await self._update_config_message(query_or_update, context, text, InlineKeyboardMarkup(kb))

    async def _show_quiz_categories_pool_menu(self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
        """Показывает меню управления пулом категорий для /quiz"""
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID)
        if not chat_id: return

        settings = await self.data_manager.get_chat_settings_async(chat_id)
        current_pool = set(settings.get('quiz_categories_pool', []))
        all_categories = self.category_manager.get_all_category_names(with_question_counts=False)
        
        # Создаем кнопки для каждой категории
        kb = []
        for cat_name in sorted(all_categories):
            if isinstance(cat_name, str):
                prefix = "✅ " if cat_name in current_pool else "☑️ "
                kb.append([InlineKeyboardButton(f"{prefix}{cat_name}", callback_data=f"{CB_ADM_QUIZ_MANAGE_CATEGORIES_POOL}:{cat_name}")])
        
        # Кнопки управления
        kb.append([
            InlineKeyboardButton("💾 Сохранить", callback_data=f"{CB_ADM_QUIZ_MANAGE_CATEGORIES_POOL}:save"),
            InlineKeyboardButton("🗑️ Очистить", callback_data=f"{CB_ADM_QUIZ_MANAGE_CATEGORIES_POOL}:clear")
        ])
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data=CB_ADM_QUIZ_SET_CATEGORIES_MODE)])
        
        text = (
            f"📝 *Управление пулом категорий для /quiz*\n\n"
            f"🎯 *Текущий выбор:* `{escape_markdown_v2(', '.join(sorted(current_pool)) if current_pool else 'пусто')}`\n\n"
            f"{escape_markdown_v2('Выберите категории для включения/исключения:')}"
        )
        
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN_V2)

    async def _send_quiz_categories_cfg_menu(self, query_or_update: Optional[Union[Update, CallbackQuery]], context: ContextTypes.DEFAULT_TYPE):
        """Отправляет меню настройки пула категорий для /quiz"""
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID)
        if not chat_id: return

        settings = await self.data_manager.get_chat_settings_async(chat_id)
        display_text = self._format_settings_display(settings, part="quiz_categories")
        header_text = f"*{escape_markdown_v2('🗂️ Настройки пула категорий для /quiz')}*"
        prompt_text = escape_markdown_v2("Выберите параметр для изменения:")
        text_for_menu = f"{header_text}\n\n{display_text}\n\n{prompt_text}"

        kb = [
            [InlineKeyboardButton("Режим выбора категорий", callback_data=CB_ADM_QUIZ_SET_CATEGORIES_MODE)],
            [InlineKeyboardButton("Управление пулом категорий", callback_data=CB_ADM_QUIZ_MANAGE_CATEGORIES_POOL)],
            [InlineKeyboardButton("⬅️ Назад в главное меню", callback_data=CB_ADM_BACK_TO_MAIN)]
        ]

        context.chat_data[CTX_CURRENT_MENU_SENDER_CB_NAME] = "_send_quiz_categories_cfg_menu"
        context.chat_data[CTX_INPUT_CANCEL_CB_DATA] = CB_ADM_BACK_TO_MAIN
        await self._update_config_message(query_or_update, context, text_for_menu, InlineKeyboardMarkup(kb))

    async def handle_quiz_menu_callbacks(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        query = update.callback_query
        await query.answer()
        action = query.data
        user_id = query.from_user.id if query.from_user else "Unknown"
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID) or "Unknown"
        
        # Логируем все нажатия кнопок на уровне DEBUG
        logger.debug(f"🔘 Админ квиз меню: {action} | Пользователь: {user_id} | Чат: {chat_id}")
        
        if not chat_id: return ConversationHandler.END

        settings = await self.data_manager.get_chat_settings_async(chat_id)
        def_s = self.app_config.default_chat_settings
        context.chat_data[CTX_CURRENT_MENU_SENDER_CB_NAME] = "_send_quiz_cfg_menu"
        context.chat_data[CTX_INPUT_CANCEL_CB_DATA] = CB_ADM_BACK_TO_QUIZ_MENU

        if action == CB_ADM_BACK_TO_MAIN:
            await self._send_main_cfg_menu(query, context)
            return CFG_MAIN_MENU
        elif action == CB_ADM_BACK_TO_QUIZ_MENU:
            await self._send_quiz_cfg_menu(query, context)
            return CFG_QUIZ_MENU
        elif action == CB_ADM_SET_DEFAULT_QUIZ_TYPE:
            current_val = settings.get('default_quiz_type', def_s['default_quiz_type'])
            kb = []
            for q_type_key in ["session", "single"]:
                q_type_config = self.app_config.quiz_types_config.get(q_type_key, {})
                q_type_name = q_type_config.get("type", q_type_key)
                prefix = "✅ " if q_type_name == current_val else "☑️ "
                kb.append([InlineKeyboardButton(f"{prefix}{q_type_name.capitalize()}", callback_data=f"{CB_ADM_SET_DEFAULT_QUIZ_TYPE_OPT}:{q_type_name}")])
            kb.append([InlineKeyboardButton("⬅️ Назад", callback_data=CB_ADM_BACK_TO_QUIZ_MENU)])
            await self._update_config_message(query, context, escape_markdown_v2("Выберите тип /quiz по умолчанию:"), InlineKeyboardMarkup(kb))
            return CFG_QUIZ_MENU
        elif action.startswith(CB_ADM_SET_DEFAULT_QUIZ_TYPE_OPT):
            val = action.split(":", 1)[1]
            await self.data_manager.update_chat_setting(chat_id, ["default_quiz_type"], val)
            await self._send_quiz_cfg_menu(query, context)
            return CFG_QUIZ_MENU
        elif action == CB_ADM_SET_DEFAULT_ANNOUNCE_QUIZ:
            current_val = settings.get('default_announce_quiz', def_s['default_announce_quiz'])
            kb = [
                [InlineKeyboardButton(f"{'✅ ' if current_val else '☑️ '}Включить анонс", callback_data=f"{CB_ADM_SET_DEFAULT_ANNOUNCE_QUIZ_OPT}:true")],
                [InlineKeyboardButton(f"{'✅ ' if not current_val else '☑️ '}Выключить анонс", callback_data=f"{CB_ADM_SET_DEFAULT_ANNOUNCE_QUIZ_OPT}:false")],
                [InlineKeyboardButton("⬅️ Назад", callback_data=CB_ADM_BACK_TO_QUIZ_MENU)]
            ]
            await self._update_config_message(query, context, escape_markdown_v2("Включить анонс для /quiz по умолчанию?"), InlineKeyboardMarkup(kb))
            return CFG_QUIZ_MENU
        elif action.startswith(CB_ADM_SET_DEFAULT_ANNOUNCE_QUIZ_OPT):
            val = action.split(":", 1)[1] == "true"
            await self.data_manager.update_chat_setting(chat_id, ["default_announce_quiz"], val)
            await self._send_quiz_cfg_menu(query, context)
            return CFG_QUIZ_MENU
        elif action == CB_ADM_QUIZ_SET_CATEGORIES_MODE:
            # Проверяем, откуда пришел запрос - из основного меню /quiz или из отдельного меню категорий
            if context.chat_data.get(CTX_CURRENT_MENU_SENDER_CB_NAME) == "_send_quiz_cfg_menu":
                # Показываем меню выбора режима категорий для обычных викторин
                current_val = settings.get('quiz_categories_mode', 'all')
                kb = [
                    [InlineKeyboardButton(f"{'✅ ' if current_val == 'all' else '☑️ '}🌐 Все категории", callback_data=f"{CB_ADM_QUIZ_SET_CATEGORIES_MODE_OPT}:all")],
                    [InlineKeyboardButton(f"{'✅ ' if current_val == 'specific' else '☑️ '}🗂️ Только выбранные", callback_data=f"{CB_ADM_QUIZ_SET_CATEGORIES_MODE_OPT}:specific")],
                    [InlineKeyboardButton(f"{'✅ ' if current_val == 'exclude' else '☑️ '}❌ Исключить выбранные", callback_data=f"{CB_ADM_QUIZ_SET_CATEGORIES_MODE_OPT}:exclude")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data=CB_ADM_BACK_TO_QUIZ_MENU)]
                ]
                await self._update_config_message(query, context, escape_markdown_v2("Выберите режим выбора категорий для /quiz:"), InlineKeyboardMarkup(kb))
                return CFG_QUIZ_MENU
            else:
                # Перенаправляем в отдельное меню категорий
                await self._send_quiz_categories_cfg_menu(query, context)
                return CFG_QUIZ_CATEGORIES_MENU
        elif action.startswith(CB_ADM_QUIZ_SET_CATEGORIES_MODE_OPT):
            # Универсальный обработчик выбора режима категорий
            mode = action.split(":", 1)[1]
            
            # Определяем контекст вызова и сохраняем в соответствующий конфиг
            current_menu = context.chat_data.get(CTX_CURRENT_MENU_SENDER_CB_NAME)
            
            if current_menu == "_send_quiz_cfg_menu":
                # Сохраняем в настройки обычных викторин
                await self.data_manager.update_chat_setting(chat_id, ["quiz_categories_mode"], mode)
                await query.answer(f"Режим обычных викторин изменен на: {mode}")
                
                # Если выбран режим specific или exclude, показываем меню управления пулом
                if mode in ['specific', 'exclude']:
                    await self._show_quiz_categories_pool_menu(query, context)
                    return CFG_QUIZ_MENU
                else:
                    await self._send_quiz_cfg_menu(query, context)
                    return CFG_QUIZ_MENU
                    
            elif current_menu == "_send_quiz_categories_cfg_menu":
                # Сохраняем в настройки обычных викторин (тот же конфиг)
                await self.data_manager.update_chat_setting(chat_id, ["quiz_categories_mode"], mode)
                await query.answer(f"Режим обычных викторин изменен на: {mode}")
                
                # Возвращаемся к меню категорий
                await self._send_quiz_categories_cfg_menu(query, context)
                return CFG_QUIZ_CATEGORIES_MENU
                
            else:
                # Неизвестный контекст - возвращаемся в главное меню
                await query.answer("Ошибка контекста")
                await self._send_main_cfg_menu(query, context)
                return CFG_MAIN_MENU
        elif action.startswith(CB_ADM_QUIZ_MANAGE_CATEGORIES_POOL):
            # Обработка управления пулом категорий
            sub_action = action.split(":", 1)[1]
            
            if sub_action in ['save', 'clear']:
                if sub_action == 'clear':
                    await self.data_manager.update_chat_setting(chat_id, ["quiz_categories_pool"], [])
                    await query.answer("Пул категорий очищен")
                else:
                    await query.answer("Пул категорий сохранен")
                # Возвращаемся к меню выбора режима
                await self._send_quiz_cfg_menu(query, context)
                return CFG_QUIZ_MENU
            else:
                # Переключение категории
                settings = await self.data_manager.get_chat_settings_async(chat_id)
                current_pool = set(settings.get('quiz_categories_pool', []))
                
                if sub_action in current_pool:
                    current_pool.remove(sub_action)
                else:
                    current_pool.add(sub_action)
                
                await self.data_manager.update_chat_setting(chat_id, ["quiz_categories_pool"], list(current_pool))
                await query.answer(f"Категория '{escape_markdown_v2(sub_action)}' {'убрана из' if sub_action in current_pool else 'добавлена в'} пул")
                # Обновляем текущее меню
                await self._show_quiz_categories_pool_menu(query, context)
                return CFG_QUIZ_MENU
        elif action == CB_ADM_BACK_TO_QUIZ_CATEGORIES_MENU:
            # Возвращаемся к меню категорий
            await self._send_quiz_categories_cfg_menu(query, context)
            return CFG_QUIZ_CATEGORIES_MENU

        elif action in [CB_ADM_SET_DEFAULT_NUM_QUESTIONS, CB_ADM_SET_DEFAULT_NUM_CATEGORIES, CB_ADM_SET_DEFAULT_OPEN_PERIOD, CB_ADM_SET_DEFAULT_ANNOUNCE_DELAY, CB_ADM_SET_DEFAULT_INTERVAL_SECONDS]:
            # Настройки по умолчанию для /quiz
            def_s = settings.get("default_chat_settings", {})
            action_to_key_mapping = {
                CB_ADM_SET_DEFAULT_NUM_QUESTIONS: (["default_num_questions"], def_s.get('default_num_questions', 10), "Кол-во вопросов в /quiz", (1, self.app_config.max_questions_per_session), 'int'),
                CB_ADM_SET_DEFAULT_NUM_CATEGORIES: (["num_categories_per_quiz"], def_s.get('num_categories_per_quiz', 3), "Кол-во категорий в /quiz", (1, 10), 'int'),
                CB_ADM_SET_DEFAULT_OPEN_PERIOD: (["default_open_period_seconds"], def_s.get('default_open_period_seconds', 30), "Время ответа в /quiz (сек)", (5, 300), 'int'),
                CB_ADM_SET_DEFAULT_ANNOUNCE_DELAY: (["default_announce_delay_seconds"], def_s.get('default_announce_delay_seconds', 30), "Задержка перед анонсом /quiz (сек)", (0, 300), 'int'),
                CB_ADM_SET_DEFAULT_INTERVAL_SECONDS: (["default_interval_seconds"], def_s.get('default_interval_seconds', 30), "Интервал между вопросами /quiz (сек)", (5, 300), 'int'),
            }
            key_path, default_val_from_def_s, prompt_text_base, (min_val, max_val), val_type = action_to_key_mapping[action]
            current_val_resolved = settings
            for k_part in key_path: current_val_resolved = current_val_resolved.get(k_part, {}) if isinstance(current_val_resolved, dict) else None # type: ignore
            if current_val_resolved is None or not isinstance(current_val_resolved, (int, float, str, bool)): current_val_resolved = default_val_from_def_s

            current_display_val_str = str(current_val_resolved)
            if key_path in [["default_open_period_seconds"], ["default_announce_delay_seconds"]] and isinstance(current_val_resolved, int):
                current_display_val_str = format_seconds_to_human_readable_time(current_val_resolved)

            escaped_prompt_base = escape_markdown_v2(prompt_text_base)
            escaped_current_val_display = escape_markdown_v2(current_display_val_str)
            escaped_range = escape_markdown_v2(f"{min_val}–{max_val}")
            prompt_to_show = (f"Введите новое значение для `{escaped_prompt_base}`\\.\nТекущее: `{escaped_current_val_display}`\\.\nДопустимый диапазон: `{escaped_range}` сек\\.")
            if key_path == ["default_num_questions"]:
                 prompt_to_show = (f"Введите новое значение для `{escaped_prompt_base}`\\.\nТекущее: `{escaped_current_val_display}`\\.\nДопустимый диапазон: `{escaped_range}`\\.")

            context.chat_data[CTX_INPUT_TARGET_KEY_PATH] = key_path
            context.chat_data[CTX_INPUT_PROMPT] = prompt_to_show
            context.chat_data[CTX_INPUT_CONSTRAINTS] = {'min': min_val, 'max': max_val, 'type': val_type}
            await self._update_config_message(query, context, prompt_to_show, InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Отмена", callback_data=CB_ADM_BACK_TO_QUIZ_MENU)]]))
            return CFG_INPUT_VALUE
        return CFG_QUIZ_MENU

    async def handle_daily_menu_callbacks(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        query = update.callback_query
        await query.answer()
        action = query.data
        user_id = query.from_user.id if query.from_user else "Unknown"
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID) or "Unknown"
        
        # Логируем все нажатия кнопок на уровне DEBUG
        logger.debug(f"🔘 Админ ежедневное меню: {action} | Пользователь: {user_id} | Чат: {chat_id}")
        
        if not chat_id: return ConversationHandler.END

        settings = await self.data_manager.get_chat_settings_async(chat_id)
        daily_s_defs_app = self.app_config.daily_quiz_defaults
        context.chat_data[CTX_CURRENT_MENU_SENDER_CB_NAME] = "_send_daily_cfg_menu"
        context.chat_data[CTX_INPUT_CANCEL_CB_DATA] = CB_ADM_BACK_TO_DAILY_MENU

        if action == CB_ADM_BACK_TO_MAIN:
            await self._send_main_cfg_menu(query, context)
            return CFG_MAIN_MENU
        if action == CB_ADM_BACK_TO_DAILY_MENU:
            await self._send_daily_cfg_menu(query, context)
            return CFG_DAILY_MENU
        elif action.startswith(CB_ADM_DAILY_TOGGLE_ENABLED):
            val_str_from_cb = action.split(":", 1)[1]
            new_enabled_state = val_str_from_cb == "true"
            await self.data_manager.update_chat_setting(chat_id, ["daily_quiz", "enabled"], new_enabled_state)
            if self.daily_quiz_scheduler_ref:
                asyncio.create_task(self._safe_reschedule_job_for_chat(chat_id))
            await self._send_daily_cfg_menu(query, context)
            return CFG_DAILY_MENU
        elif action == CB_ADM_DAILY_MANAGE_TIMES:
            await self._send_daily_times_menu(query, context)
            return CFG_DAILY_TIMES_MENU
        elif action == CB_ADM_DAILY_SET_CATEGORIES_MODE:
            current_daily_s_in_chat = settings.get("daily_quiz", {})
            current_mode = current_daily_s_in_chat.get("categories_mode", daily_s_defs_app['categories_mode'])
            modes_map = {"random": "🎲 Случайные", "specific": "🗂️ Выбранные", "all_enabled": "✅ Все разрешенные"}
            kb = []
            for mode_val_internal, mode_text_display in modes_map.items():
                prefix = "✅ " if mode_val_internal == current_mode else "☑️ "
                kb.append([InlineKeyboardButton(f"{prefix}{mode_text_display}", callback_data=f"{CB_ADM_DAILY_SET_CATEGORIES_MODE_OPT}:{mode_val_internal}")])
            kb.append([InlineKeyboardButton("⬅️ Назад", callback_data=CB_ADM_BACK_TO_DAILY_MENU)])
            categories_mode_prompt = escape_markdown_v2("Выберите режим категорий для ежедневной викторины:")
            await self._update_config_message(query, context, categories_mode_prompt, InlineKeyboardMarkup(kb))
            return CFG_DAILY_MENU
        elif action.startswith(CB_ADM_DAILY_SET_CATEGORIES_MODE_OPT):
            mode_val_selected = action.split(":",1)[1]
            await self.data_manager.update_chat_setting(chat_id, ["daily_quiz", "categories_mode"], mode_val_selected)
            if self.daily_quiz_scheduler_ref: asyncio.create_task(self._safe_reschedule_job_for_chat(chat_id))

            if mode_val_selected == "random":
                key_path, default_val, prompt_text_base, (min_val, max_val), val_type = (
                    ["daily_quiz", "num_random_categories"], daily_s_defs_app['num_random_categories'],
                    "Кол-во случайных категорий (ежедн.)", (1,10), 'int'
                )
                current_val = settings.get("daily_quiz", {}).get(key_path[1], default_val)
                escaped_prompt_base = escape_markdown_v2(prompt_text_base)
                escaped_current_val = escape_markdown_v2(str(current_val))
                escaped_range = escape_markdown_v2(f"{min_val}–{max_val}")
                prompt_to_show = (f"Введите новое значение для `{escaped_prompt_base}`\\.\nТекущее: `{escaped_current_val}`\\.\nДопустимый диапазон: `{escaped_range}`\\.")
                context.chat_data[CTX_INPUT_TARGET_KEY_PATH] = key_path
                context.chat_data[CTX_INPUT_PROMPT] = prompt_to_show
                context.chat_data[CTX_INPUT_CONSTRAINTS] = {'min': min_val, 'max': max_val, 'type': val_type}
                await self._update_config_message(query, context, prompt_to_show, InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Отмена", callback_data=CB_ADM_BACK_TO_DAILY_MENU)]]))
                return CFG_INPUT_VALUE
            elif mode_val_selected == "specific":
                current_daily_s_for_spec = settings.get("daily_quiz", {})
                context.chat_data[CTX_CATEGORY_SELECTION_MODE] = 'daily_specific_categories'
                context.chat_data[CTX_CATEGORY_SELECTION_TITLE] = escape_markdown_v2('категорий для ежедневной викторины')
                context.chat_data[CTX_TEMP_CATEGORY_SELECTION] = set(current_daily_s_for_spec.get('specific_categories', []))
                await self._send_category_selection_menu(query, context)
                return CFG_SELECT_GENERAL_CATEGORIES
            await self._send_daily_cfg_menu(query, context)
            return CFG_DAILY_MENU
        elif action in [CB_ADM_DAILY_SET_NUM_QUESTIONS, CB_ADM_DAILY_SET_INTERVAL_SECONDS, CB_ADM_DAILY_SET_POLL_OPEN_SECONDS, CB_ADM_DAILY_SET_NUM_RANDOM_CATEGORIES]:
            key_map_daily = {
                CB_ADM_DAILY_SET_NUM_QUESTIONS: (["daily_quiz", "num_questions"], daily_s_defs_app['num_questions'], "Кол-во вопросов (ежедн.)", (1, self.app_config.max_questions_per_session), 'int'),
                CB_ADM_DAILY_SET_INTERVAL_SECONDS: (["daily_quiz", "interval_seconds"], daily_s_defs_app['interval_seconds'], "Интервал между вопросами (ежедн. сек)", (10, 3600), 'int'), 
                CB_ADM_DAILY_SET_POLL_OPEN_SECONDS: (["daily_quiz", "poll_open_seconds"], daily_s_defs_app.get('poll_open_seconds',600) , "Время на ответ (ежедн. сек)", (30, 3600 * 2), 'int'), 
                CB_ADM_DAILY_SET_NUM_RANDOM_CATEGORIES: (["daily_quiz", "num_random_categories"], daily_s_defs_app['num_random_categories'], "Кол-во случайных категорий (ежедн.)", (1,10), 'int')
            }
            key_path, default_val, prompt_text_base, (min_val, max_val), val_type = key_map_daily[action]
            current_daily_s_val_resolved = settings.get("daily_quiz", {})
            current_val = current_daily_s_val_resolved.get(key_path[1], default_val)

            current_display_val_str = str(current_val)
            unit_for_range = "сек"
            if key_path in [["daily_quiz", "interval_seconds"], ["daily_quiz", "poll_open_seconds"]] and isinstance(current_val, int):
                current_display_val_str = format_seconds_to_human_readable_time(current_val)
            elif key_path == ["daily_quiz", "num_questions"] or key_path == ["daily_quiz", "num_random_categories"]:
                unit_for_range = ""

            escaped_prompt_base = escape_markdown_v2(prompt_text_base.replace(" (сек)", "")) 
            escaped_current_val_display = escape_markdown_v2(current_display_val_str)
            escaped_range = escape_markdown_v2(f"{min_val}–{max_val}")
            prompt_to_show = (f"Введите новое значение для `{escaped_prompt_base}`\\.\nТекущее: `{escaped_current_val_display}`\\.\nДопустимый диапазон: `{escaped_range}` {escape_markdown_v2(unit_for_range)}\\.")
            if key_path == ["daily_quiz", "interval_seconds"] or key_path == ["daily_quiz", "poll_open_seconds"]:
                 prompt_to_show += escape_markdown_v2("\nЗначение вводить в секундах.")

            context.chat_data[CTX_INPUT_TARGET_KEY_PATH] = key_path
            context.chat_data[CTX_INPUT_PROMPT] = prompt_to_show
            context.chat_data[CTX_INPUT_CONSTRAINTS] = {'min': min_val, 'max': max_val, 'type': val_type}
            await self._update_config_message(query, context, prompt_to_show, InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Отмена", callback_data=CB_ADM_BACK_TO_DAILY_MENU)]]))
            return CFG_INPUT_VALUE
        return CFG_DAILY_MENU

    async def _send_daily_times_menu(self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID)
        if not chat_id: return

        settings = await self.data_manager.get_chat_settings_async(chat_id)
        daily_settings = settings.setdefault("daily_quiz", {})
        times_list_raw = daily_settings.setdefault("times_msk", [])
        
        # Исправляем данные, если times_msk сохранено как строка вместо массива
        if isinstance(times_list_raw, str):
            # Парсим строку типа "09:00" в объект {"hour": 9, "minute": 0}
            try:
                hour, minute = times_list_raw.split(":")
                times_list = [{"hour": int(hour), "minute": int(minute)}]
                # Сохраняем исправленные данные
                daily_settings["times_msk"] = times_list
                await self.data_manager.update_chat_setting(chat_id, ["daily_quiz", "times_msk"], times_list)
            except:
                times_list = []
        elif not isinstance(times_list_raw, list):
            times_list = []
        else:
            times_list: List[Dict[str, int]] = times_list_raw
        
        times_list.sort(key=lambda t: (t.get("hour",0), t.get("minute",0)))

        # Получаем текущий timezone и его отображаемое название
        current_timezone = daily_settings.get("timezone", "Europe/Moscow")
        timezone_display = self._get_timezone_display_name(current_timezone)

        text_lines = [f"*{escape_markdown_v2(f'⏰ Управление временами запуска Ежедневной Викторины ({timezone_display})')}*"]
        kb = []

        if times_list:
            text_lines.append(escape_markdown_v2("Текущие времена запуска:"))
            for i, time_entry in enumerate(times_list):
                h, m = time_entry.get("hour",0), time_entry.get("minute",0)
                time_str_escaped = escape_markdown_v2(f"{h:02d}:{m:02d}")
                text_lines.append(f"{escape_markdown_v2(f'{i+1}.')} {time_str_escaped}")
                kb.append([InlineKeyboardButton(f"❌ Удалить {time_str_escaped}", callback_data=f"{CB_ADM_DAILY_TIME_REMOVE}:{i}")])
        else:
            text_lines.append(escape_markdown_v2("Времена запуска еще не добавлены."))

        max_times_allowed = self.app_config.max_daily_quiz_times_per_chat
        if len(times_list) < max_times_allowed:
            kb.append([InlineKeyboardButton("➕ Добавить время", callback_data=CB_ADM_DAILY_TIME_ADD)])
        else:
             text_lines.append(escape_markdown_v2(f"Достигнут лимит в {max_times_allowed} {pluralize(max_times_allowed, 'настройку', 'настройки', 'настроек')} времени."))

        # Добавляем кнопку выбора часового пояса
        current_timezone = daily_settings.get("timezone", "Europe/Moscow")
        timezone_display = self._get_timezone_display_name(current_timezone)
        kb.append([InlineKeyboardButton(f"🌍 Часовой пояс: {timezone_display}", callback_data=CB_ADM_DAILY_TIME_SET_TIMEZONE)])

        kb.append([InlineKeyboardButton("⬅️ Назад в настройки Ежедн.Викторины", callback_data=CB_ADM_BACK_TO_DAILY_MENU)])

        final_text = "\n".join(text_lines)
        context.chat_data[CTX_CURRENT_MENU_SENDER_CB_NAME] = "_send_daily_times_menu"
        context.chat_data[CTX_INPUT_CANCEL_CB_DATA] = CB_ADM_DAILY_TIME_BACK_TO_LIST
        await self._update_config_message(query, context, final_text, InlineKeyboardMarkup(kb))

    def _get_timezone_display_name(self, timezone: str) -> str:
        """Возвращает отображаемое название часового пояса"""
        timezone_names = {
            "America/New_York": "Нью-Йорк (UTC-5)",
            "America/Sao_Paulo": "Сан-Паулу (UTC-3)",
            "Atlantic/Azores": "Азорские о-ва (UTC-2)",
            "Atlantic/South_Georgia": "Южная Георгия (UTC-1)",
            "Europe/London": "Лондон (UTC+0)",
            "Europe/Paris": "Париж (UTC+1)",
            "Europe/Kaliningrad": "Калининград (UTC+2)",
            "Europe/Moscow": "Москва (UTC+3)",
            "Asia/Dubai": "Дубай (UTC+4)",
            "Asia/Tashkent": "Ташкент (UTC+5)",
            "Europe/Berlin": "Берлин (UTC+1)",
            "America/Los_Angeles": "Лос-Анджелес (UTC-8)",
            "Asia/Tokyo": "Токио (UTC+9)",
            "Asia/Shanghai": "Шанхай (UTC+8)",
            "Australia/Sydney": "Сидней (UTC+10)",
        }
        return timezone_names.get(timezone, f"{timezone}")

    async def handle_daily_times_menu_callbacks(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        query = update.callback_query
        await query.answer()
        action = query.data
        user_id = query.from_user.id if query.from_user else "Unknown"
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID) or "Unknown"
        
        # Логируем только важные действия на уровне INFO, остальные на DEBUG
        if action in [CB_ADM_DAILY_TIME_ADD, CB_ADM_DAILY_TIME_REMOVE]:
            logger.info(f"Админ {user_id} в чате {chat_id}: {action}")
        else:
            logger.debug(f"🔘 Админ время ежедневное: {action} | Пользователь: {user_id} | Чат: {chat_id}")
        
        if not chat_id: return ConversationHandler.END

        settings = await self.data_manager.get_chat_settings_async(chat_id)
        daily_settings = settings.setdefault("daily_quiz", {})
        times_list: List[Dict[str, int]] = daily_settings.setdefault("times_msk", [])
        times_list.sort(key=lambda t: (t.get("hour",0), t.get("minute",0)))

        context.chat_data[CTX_CURRENT_MENU_SENDER_CB_NAME] = "_send_daily_times_menu"
        context.chat_data[CTX_INPUT_CANCEL_CB_DATA] = CB_ADM_DAILY_TIME_BACK_TO_LIST

        if action == CB_ADM_BACK_TO_DAILY_MENU:
            await self._send_daily_cfg_menu(query, context)
            return CFG_DAILY_MENU
        elif action == CB_ADM_DAILY_TIME_BACK_TO_LIST:
            await self._send_daily_times_menu(query, context)
            return CFG_DAILY_TIMES_MENU
        elif action == CB_ADM_DAILY_TIME_ADD:
            max_times = self.app_config.max_daily_quiz_times_per_chat
            if len(times_list) >= max_times:
                await query.answer(f"Достигнут лимит ({max_times}) времен.", show_alert=True)
                await self._send_daily_times_menu(query, context)
                return CFG_DAILY_TIMES_MENU

            prompt_for_new_time = escape_markdown_v2("Введите новое время для ежедневной викторины в формате ЧЧ:ММ (например, 14:30).")
            context.chat_data[CTX_INPUT_TARGET_KEY_PATH] = ["daily_quiz", "times_msk"]
            context.chat_data[CTX_INPUT_PROMPT] = prompt_for_new_time
            context.chat_data[CTX_INPUT_CONSTRAINTS] = {'type': 'time', 'action': 'add_to_list'}
            await self._update_config_message(query, context, prompt_for_new_time, InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Отмена", callback_data=CB_ADM_DAILY_TIME_BACK_TO_LIST)]]))
            return CFG_INPUT_VALUE
        elif action.startswith(CB_ADM_DAILY_TIME_REMOVE):
            try:
                time_index_to_remove_str = action.split(":",1)[1]
                time_index_to_remove = int(time_index_to_remove_str)
                if 0 <= time_index_to_remove < len(times_list):
                    if self.data_manager.postgres_storage and len(times_list) == 1 and daily_settings.get("enabled"):
                        await query.answer("Сначала отключите ежедневный квиз или добавьте другое время.", show_alert=True)
                        await self._send_daily_times_menu(query, context)
                        return CFG_DAILY_TIMES_MENU
                    removed_time = times_list.pop(time_index_to_remove)
                    logger.info(f"Удалено время {removed_time} из списка для чата {chat_id}")
                    await self.data_manager.update_chat_setting(chat_id, ["daily_quiz", "times_msk"], times_list)
                    if self.daily_quiz_scheduler_ref:
                        asyncio.create_task(self._safe_reschedule_job_for_chat(chat_id))
                else: await query.answer("Ошибка: неверный индекс времени для удаления.", show_alert=True)
            except (ValueError, IndexError) as e:
                logger.error(f"Ошибка при удалении времени: {e}. Action: {action}")
                await query.answer("Ошибка при удалении времени.", show_alert=True)
            await self._send_daily_times_menu(query, context)
            return CFG_DAILY_TIMES_MENU
        elif action == CB_ADM_DAILY_TIME_SET_TIMEZONE:
            await self._send_timezone_selection_menu(query, context)
            return CFG_DAILY_TIMEZONE_MENU
        elif action.startswith(f"{CB_ADM_DAILY_TIME_SET_TIMEZONE}:"):
            # Обработка выбора часового пояса
            try:
                selected_timezone = action.split(":", 1)[1]

                # Получаем текущий часовой пояс перед изменением
                current_timezone = daily_settings.get("timezone", "Europe/Moscow")

                # Проверяем, изменился ли часовой пояс
                timezone_changed = current_timezone != selected_timezone

                if timezone_changed:
                    daily_settings["timezone"] = selected_timezone
                    await self.data_manager.update_chat_setting(chat_id, ["daily_quiz", "timezone"], selected_timezone)

                    # Используем умную перепланировку при смене часового пояса
                    if self.daily_quiz_scheduler_ref:
                        asyncio.create_task(self._safe_reschedule_job_for_chat(
                            chat_id,
                            timezone_change=True,
                            old_timezone=current_timezone,
                            new_timezone=selected_timezone
                        ))

                    await query.answer(f"Часовой пояс изменён на {self._get_timezone_display_name(selected_timezone)}", show_alert=True)
                else:
                    await query.answer(f"Часовой пояс уже установлен на {self._get_timezone_display_name(selected_timezone)}", show_alert=True)

                await self._send_daily_times_menu(query, context)
                return CFG_DAILY_TIMES_MENU
            except Exception as e:
                logger.error(f"Ошибка при изменении часового пояса: {e}")
                await query.answer("Ошибка при изменении часового пояса", show_alert=True)
                await self._send_daily_times_menu(query, context)
                return CFG_DAILY_TIMES_MENU
        return CFG_DAILY_TIMES_MENU

    async def _send_timezone_selection_menu(self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Отправляет меню выбора часового пояса"""
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID)
        if not chat_id:
            return

        settings = await self.data_manager.get_chat_settings_async(chat_id)

        # Определяем контекст: мудрость дня или ежедневная викторина
        current_menu = context.chat_data.get(CTX_CURRENT_MENU_SENDER_CB_NAME, "")
        if current_menu == "_send_wisdom_menu":
            # Контекст мудрости дня
            current_timezone = settings.get("daily_quiz", {}).get("timezone", "Europe/Moscow")
            timezone_callback_prefix = CB_ADM_WISDOM_SET_TIMEZONE
            back_callback = CB_ADM_WISDOM_MENU
            title = "🌍 Выбор часового пояса для мудрости дня"
        else:
            # Контекст ежедневной викторины
            daily_settings = settings.setdefault("daily_quiz", {})
            current_timezone = daily_settings.get("timezone", "Europe/Moscow")
            timezone_callback_prefix = CB_ADM_DAILY_TIME_SET_TIMEZONE
            back_callback = CB_ADM_DAILY_TIME_BACK_TO_LIST
            title = "🌍 Выбор часового пояса для викторины"
        
        text_lines = [
            f"*{escape_markdown_v2(title)}*",
            "",
            f"Текущий часовой пояс: *{escape_markdown_v2(self._get_timezone_display_name(current_timezone))}*",
            "",
            "Выберите новый часовой пояс:"
        ]
        
        # Создаём клавиатуру с часовыми поясами (полный диапазон UTC-5 до UTC+5)
        kb = []
        timezones = [
            ("America/New_York", "🇺🇸 Нью-Йорк (UTC-5)"),
            ("America/Sao_Paulo", "🇧🇷 Сан-Паулу (UTC-3)"),
            ("Atlantic/Azores", "🇵🇹 Азорские о-ва (UTC-2)"),
            ("Atlantic/South_Georgia", "🇬🇸 Южная Георгия (UTC-1)"),
            ("Europe/London", "🇬🇧 Лондон (UTC+0)"),
            ("Europe/Paris", "🇫🇷 Париж (UTC+1)"),
            ("Europe/Kaliningrad", "🇷🇺 Калининград (UTC+2)"),
            ("Europe/Moscow", "🇷🇺 Москва (UTC+3)"),
            ("Asia/Dubai", "🇦🇪 Дубай (UTC+4)"),
            ("Asia/Tashkent", "🇺🇿 Ташкент (UTC+5)"),
        ]
        
        # Размещаем кнопки по 2 в ряд
        for i in range(0, len(timezones), 2):
            row = []
            row.append(InlineKeyboardButton(
                timezones[i][1],
                callback_data=f"{timezone_callback_prefix}:{timezones[i][0]}"
            ))
            if i + 1 < len(timezones):
                row.append(InlineKeyboardButton(
                    timezones[i + 1][1],
                    callback_data=f"{timezone_callback_prefix}:{timezones[i + 1][0]}"
                ))
            kb.append(row)
        
        # Кнопка "Назад"
        back_button_text = "⬅️ Назад к меню мудрости дня" if current_menu == "_send_wisdom_menu" else "⬅️ Назад к временам"
        kb.append([InlineKeyboardButton(back_button_text, callback_data=back_callback)])
        
        final_text = "\n".join(text_lines)
        context.chat_data[CTX_CURRENT_MENU_SENDER_CB_NAME] = "_send_timezone_selection_menu"
        context.chat_data[CTX_INPUT_CANCEL_CB_DATA] = back_callback
        
        await self._update_config_message(query, context, final_text, InlineKeyboardMarkup(kb))

    async def handle_confirm_reset_callbacks(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        query = update.callback_query
        await query.answer()
        action = query.data
        user_id = query.from_user.id if query.from_user else "Unknown"
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID) or "Unknown"
        
        # Логируем все нажатия кнопок на уровне DEBUG
        logger.debug(f"🔘 Админ подтверждение сброса: {action} | Пользователь: {user_id} | Чат: {chat_id}")
        
        if not chat_id: return ConversationHandler.END

        context.chat_data[CTX_CURRENT_MENU_SENDER_CB_NAME] = "_send_main_cfg_menu"
        context.chat_data[CTX_INPUT_CANCEL_CB_DATA] = CB_ADM_BACK_TO_MAIN

        if action == CB_ADM_EXECUTE_RESET_SETTINGS:
            await self.data_manager.reset_chat_settings(chat_id)
            if self.daily_quiz_scheduler_ref:
                asyncio.create_task(self._safe_reschedule_job_for_chat(chat_id))
            await self._send_main_cfg_menu(query, context)
            return CFG_MAIN_MENU
        elif action == CB_ADM_BACK_TO_MAIN:
            await self._send_main_cfg_menu(query, context)
            return CFG_MAIN_MENU
        return CFG_CONFIRM_RESET



    async def cancel_config_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        final_message_unescaped = "Настройка отменена."
        final_message_escaped = escape_markdown_v2(final_message_unescaped)
        query = update.callback_query
        chat_id_for_ops = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID)
        original_menu_msg_id = context.chat_data.get(CTX_ADMIN_CFG_MSG_ID)

        if query:
            await query.answer()
            if query.message and original_menu_msg_id == query.message.message_id:
                try: await query.edit_message_text(final_message_escaped, reply_markup=None, parse_mode=ParseMode.MARKDOWN_V2)
                except BadRequest as e_br:
                    if "Message is not modified" not in str(e_br).lower(): logger.warning(f"Ошибка BadRequest при редактировании на отмену: {e_br}")
                except Exception as e_edit_cancel: logger.error(f"Ошибка редактирования при отмене диалога (кнопка): {e_edit_cancel}")
            elif chat_id_for_ops :
                 try: await safe_send_message(
                    bot=context.bot,
                    chat_id=chat_id_for_ops,
                    text=final_message_escaped,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                 except Exception as e_send_cb_other: logger.error(f"Не удалось отправить сообщение отмены (кнопка, другое сообщение): {e_send_cb_other}")
        elif update.message:
            if chat_id_for_ops:
                if original_menu_msg_id:
                    try: await context.bot.delete_message(chat_id_for_ops, original_menu_msg_id)
                    except Exception as e_del_cfg_cmd: logger.debug(f"Не удалось удалить сообщение конфига при отмене (команда /cancel): {e_del_cfg_cmd}")
                try: await safe_send_message(
                    bot=context.bot,
                    chat_id=chat_id_for_ops,
                    text=final_message_escaped,
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_to_message_id=update.message.message_id
                )
                except Exception as e_send_cancel_cmd: logger.error(f"Не удалось отправить сообщение отмены (команда /cancel): {e_send_cancel_cmd}")
            else:
                try: await update.message.reply_text(final_message_escaped, parse_mode=ParseMode.MARKDOWN_V2)
                except Exception as e_send_reply_cancel: logger.error(f"Не удалось отправить reply на отмену (команда /cancel): {e_send_reply_cancel}")

        logger.info(f"Диалог настройки отменен для чата {chat_id_for_ops if chat_id_for_ops else 'N/A'}.")
        context.chat_data.clear()
        return ConversationHandler.END



    def get_handlers(self) -> List[Any]:
        from modules.telegram_menu import conversation_entry, home_fallbacks
        cancel_handler_for_conv = CommandHandler(self.app_config.commands.cancel, self.cancel_config_conversation)

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler(self.app_config.commands.admin_settings, self.admin_settings_entry),
                CallbackQueryHandler(conversation_entry(self.admin_settings_entry, self.app_config.commands.admin_settings), pattern=r'^(nav:settings|start_settings)$'),
                CommandHandler('start', conversation_entry(self.admin_settings_entry, self.app_config.commands.admin_settings), filters=filters.Regex(r'^/start(?:@\w+)? settings$'))],
            states={
                CFG_MAIN_MENU: [CallbackQueryHandler(self.handle_main_menu_callbacks, pattern=f"^{CB_ADM_}")],
                CFG_QUIZ_MENU: [CallbackQueryHandler(self.handle_quiz_menu_callbacks, pattern=f"^{CB_ADM_}")],
                CFG_QUIZ_CATEGORIES_MENU: [CallbackQueryHandler(self.handle_quiz_categories_menu_callbacks, pattern=f"^{CB_ADM_}")],
                CFG_QUIZ_CATEGORIES_POOL_SELECTION: [
                    CallbackQueryHandler(self.handle_quiz_menu_callbacks, pattern=f"^{CB_ADM_QUIZ_MANAGE_CATEGORIES_POOL}"),
                    CallbackQueryHandler(self.handle_quiz_menu_callbacks, pattern=f"^{CB_ADM_QUIZ_SET_CATEGORIES_MODE}$"),
                    CallbackQueryHandler(self.handle_quiz_categories_menu_callbacks, pattern=f"^{CB_ADM_BACK_TO_QUIZ_CATEGORIES_MENU}$")
                ],
                CFG_INPUT_VALUE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_input_value),
                    CallbackQueryHandler(self.handle_main_menu_callbacks, pattern=f"^{CB_ADM_BACK_TO_MAIN}$"),
                    CallbackQueryHandler(self.handle_daily_menu_callbacks, pattern=f"^{CB_ADM_BACK_TO_DAILY_MENU}$"),
                    CallbackQueryHandler(self.handle_quiz_menu_callbacks, pattern=f"^{CB_ADM_BACK_TO_QUIZ_MENU}$"),
                    CallbackQueryHandler(self.handle_quiz_categories_menu_callbacks, pattern=f"^{CB_ADM_BACK_TO_QUIZ_CATEGORIES_MENU}$"),
                    CallbackQueryHandler(self.handle_daily_times_menu_callbacks, pattern=f"^{CB_ADM_DAILY_TIME_BACK_TO_LIST}$")
                ],
                CFG_SELECT_GENERAL_CATEGORIES: [
                    CallbackQueryHandler(self.handle_category_selection_callback, pattern=f"^{CB_ADM_CAT_SEL_}"),
                    CallbackQueryHandler(self.handle_main_menu_callbacks, pattern=f"^{CB_ADM_BACK_TO_MAIN}$"),
                    CallbackQueryHandler(self.handle_daily_menu_callbacks, pattern=f"^{CB_ADM_BACK_TO_DAILY_MENU}$")
                ],
                CFG_DAILY_MENU: [CallbackQueryHandler(self.handle_daily_menu_callbacks, pattern=f"^{CB_ADM_}")],
                CFG_CONFIRM_RESET: [CallbackQueryHandler(self.handle_confirm_reset_callbacks, pattern=f"^{CB_ADM_}")],
                CFG_DAILY_TIMES_MENU: [
                    CallbackQueryHandler(self.handle_daily_times_menu_callbacks, pattern=f"^{CB_ADM_DAILY_TIME_}"),
                    CallbackQueryHandler(self.handle_daily_menu_callbacks, pattern=f"^{CB_ADM_BACK_TO_DAILY_MENU}$")
                ],
                CFG_DAILY_TIMEZONE_MENU: [
                    CallbackQueryHandler(self.handle_daily_times_menu_callbacks, pattern=f"^{CB_ADM_DAILY_TIME_}"),
                    CallbackQueryHandler(self.handle_daily_times_menu_callbacks, pattern=f"^{CB_ADM_DAILY_TIME_SET_TIMEZONE}:"),
                    CallbackQueryHandler(self.handle_daily_menu_callbacks, pattern=f"^{CB_ADM_BACK_TO_DAILY_MENU}$")
                ],
                CFG_WISDOM_MENU: [
                    CallbackQueryHandler(self.handle_main_menu_callbacks, pattern=f"^{CB_ADM_WISDOM_}"),
                    CallbackQueryHandler(self.handle_main_menu_callbacks, pattern=f"^{CB_ADM_BACK_TO_MAIN}$"),
                    CallbackQueryHandler(self.handle_main_menu_callbacks, pattern=f"^{CB_ADM_WISDOM_BACK_TO_MAIN}$")
                ],
                CFG_WISDOM_TIME_INPUT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_input_value),
                    CallbackQueryHandler(self.handle_main_menu_callbacks, pattern=f"^{CB_ADM_WISDOM_MENU}$"),
                    CallbackQueryHandler(self.handle_main_menu_callbacks, pattern=f"^{CB_ADM_BACK_TO_MAIN}$"),
                    CallbackQueryHandler(self.handle_main_menu_callbacks, pattern=f"^{CB_ADM_WISDOM_BACK_TO_MAIN}$")
                ],
                CFG_WISDOM_TIMEZONE_MENU: [
                    CallbackQueryHandler(self.handle_main_menu_callbacks, pattern=f"^{CB_ADM_WISDOM_}"),
                    CallbackQueryHandler(self.handle_main_menu_callbacks, pattern=f"^{CB_ADM_BACK_TO_MAIN}$"),
                    CallbackQueryHandler(self.handle_main_menu_callbacks, pattern=f"^{CB_ADM_WISDOM_BACK_TO_MAIN}$"),
                    CallbackQueryHandler(self.handle_main_menu_callbacks, pattern=f"^{CB_ADM_WISDOM_MENU}$")
                ],
            },
            fallbacks=[*home_fallbacks(), cancel_handler_for_conv],
            per_chat=True, per_user=True, name="admin_settings_conversation", persistent=True, allow_reentry=True
        )
        return [
            conv_handler,
        ]

    async def handle_quiz_categories_menu_callbacks(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        """Обработчик callback'ов для меню настройки пула категорий /quiz"""
        query = update.callback_query
        await query.answer()
        action = query.data
        user_id = query.from_user.id if query.from_user else "Unknown"
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID) or "Unknown"
        
        # Логируем все нажатия кнопок на уровне DEBUG
        logger.debug(f"🔘 Админ квиз категории меню: {action} | Пользователь: {user_id} | Чат: {chat_id}")
        
        if not chat_id: return ConversationHandler.END

        settings = await self.data_manager.get_chat_settings_async(chat_id)
        def_s = self.app_config.default_chat_settings
        context.chat_data[CTX_CURRENT_MENU_SENDER_CB_NAME] = "_send_quiz_categories_cfg_menu"
        context.chat_data[CTX_INPUT_CANCEL_CB_DATA] = CB_ADM_BACK_TO_QUIZ_CATEGORIES_MENU

        if action == CB_ADM_BACK_TO_MAIN:
            await self._send_main_cfg_menu(query, context)
            return CFG_MAIN_MENU
        # Убрано: дублирующийся обработчик CB_ADM_QUIZ_SET_CATEGORIES_MODE - теперь обрабатывается универсально

        elif action == CB_ADM_QUIZ_MANAGE_CATEGORIES_POOL:
            # Переходим к выбору категорий
            context.chat_data[CTX_QUIZ_CATEGORY_SELECTION_MODE] = 'quiz_categories_pool'
            context.chat_data[CTX_QUIZ_TEMP_CATEGORY_SELECTION] = set(settings.get('quiz_categories_pool', []))
            await self._send_quiz_categories_pool_selection_menu(query, context)
            return CFG_QUIZ_CATEGORIES_POOL_SELECTION

        return CFG_QUIZ_CATEGORIES_MENU

    async def _send_quiz_categories_pool_selection_menu(self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет меню выбора категорий для пула /quiz"""
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID)
        if not chat_id: return

        current_selection = context.chat_data.get(CTX_QUIZ_TEMP_CATEGORY_SELECTION, set())
        all_categories = self.category_manager.get_all_category_names()
        
        header_text = f"*{escape_markdown_v2('🗂️ Выбор категорий для пула /quiz')}*"
        current_mode = context.chat_data.get(CTX_QUIZ_CATEGORY_SELECTION_MODE, 'quiz_categories_pool')
        
        if current_mode == 'quiz_categories_pool':
            mode_text = "Выберите категории для включения/исключения в пул /quiz"
        else:
            mode_text = "Выбор категорий"
        
        prompt_text = escape_markdown_v2(mode_text)
        current_selection_text = escape_markdown_v2(f"Текущий выбор: {', '.join(sorted(current_selection)) if current_selection else 'пусто'}")
        
        text = f"{header_text}\n\n{prompt_text}\n\n{current_selection_text}"

        # Создаем кнопки для каждой категории
        kb = []
        for category in sorted(all_categories):
            prefix = "✅ " if category in current_selection else "☑️ "
            kb.append([InlineKeyboardButton(f"{prefix}{category}", callback_data=f"{CB_ADM_QUIZ_CAT_POOL_TOGGLE}:{category}")])

        # Кнопки управления
        kb.append([
            InlineKeyboardButton("💾 Сохранить", callback_data=CB_ADM_QUIZ_CAT_POOL_SAVE),
            InlineKeyboardButton("🗑️ Очистить", callback_data=CB_ADM_QUIZ_CAT_POOL_CLEAR)
        ])
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data=CB_ADM_BACK_TO_QUIZ_CATEGORIES_MENU)])

        await self._update_config_message(query, context, text, InlineKeyboardMarkup(kb))

    async def handle_quiz_categories_pool_selection_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        """Обработчик callback'ов для выбора категорий пула /quiz"""
        query = update.callback_query
        await query.answer()
        action = query.data
        user_id = query.from_user.id if query.from_user else "Unknown"
        chat_id = context.chat_data.get(CTX_ADMIN_CFG_CHAT_ID) or "Unknown"
        
        # Логируем все нажатия кнопок на уровне DEBUG
        logger.debug(f"🔘 Админ квиз категории пул: {action} | Пользователь: {user_id} | Чат: {chat_id}")
        
        if not chat_id: return ConversationHandler.END

        current_selection = context.chat_data.get(CTX_QUIZ_TEMP_CATEGORY_SELECTION, set())

        if action == CB_ADM_BACK_TO_QUIZ_CATEGORIES_MENU:
            await self._send_quiz_categories_cfg_menu(query, context)
            return CFG_QUIZ_CATEGORIES_MENU
        elif action.startswith(CB_ADM_QUIZ_CAT_POOL_TOGGLE):
            category = action.split(":", 1)[1]
            if category in current_selection:
                current_selection.remove(category)
            else:
                current_selection.add(category)
            context.chat_data[CTX_QUIZ_TEMP_CATEGORY_SELECTION] = current_selection
            await self._send_quiz_categories_pool_selection_menu(query, context)
            return CFG_QUIZ_CATEGORIES_POOL_SELECTION
        elif action == CB_ADM_QUIZ_CAT_POOL_SAVE:
            # Сохраняем выбранные категории
            await self.data_manager.update_chat_setting(chat_id, ["quiz_categories_pool"], list(current_selection))
            await self._send_quiz_categories_cfg_menu(query, context)
            return CFG_QUIZ_CATEGORIES_MENU
        elif action == CB_ADM_QUIZ_CAT_POOL_CLEAR:
            # Очищаем выбор
            context.chat_data[CTX_QUIZ_TEMP_CATEGORY_SELECTION] = set()
            await self._send_quiz_categories_pool_selection_menu(query, context)
            return CFG_QUIZ_CATEGORIES_POOL_SELECTION

        return CFG_QUIZ_CATEGORIES_POOL_SELECTION
