"""
Модуль для установки команд бота в Telegram Bot API.
Отвечает за регистрацию всех команд бота для различных скоупов.
"""

import logging
import asyncio
from typing import TYPE_CHECKING

from telegram import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllChatAdministrators,
)
from telegram.error import TimedOut, NetworkError, TelegramError

if TYPE_CHECKING:
    from telegram.ext import Application
    from app_config import AppConfig

logger = logging.getLogger(__name__)


async def setup_bot_commands(application: "Application", app_config: "AppConfig") -> None:
    """
    Устанавливает команды бота для всех скоупов.
    Должна вызываться после регистрации всех обработчиков, но до запуска бота.
    
    Args:
        application: Экземпляр Application из python-telegram-bot
        app_config: Конфигурация приложения с настройками команд
    """
    # Команды для обычных пользователей и админов чатов
    bot_commands = [
        # Основные команды
        BotCommand(app_config.commands.start, "🚀 Начать работу с ботом"),
        BotCommand(app_config.commands.help, "ℹ️ Помощь по командам"),
        BotCommand(app_config.commands.quiz, "🏁 Начать викторину"),
        BotCommand("mafia", "🌒 Собрать стол «Ночного города»"),
        BotCommand(app_config.commands.categories, "📚 Список категорий"),
        BotCommand(app_config.commands.category_stats, "📊 Статистика категорий"),
        BotCommand(app_config.commands.chatcategories, "🎲 Очередь категорий с весами"),
        BotCommand(app_config.commands.top, "🏆 Показать рейтинг"),
        BotCommand(app_config.commands.global_top, "🏆 Показать глобальный рейтинг"),
        BotCommand(app_config.commands.mystats, "📊 Показать вашу статистику"),
        BotCommand(app_config.commands.stop_quiz, "🛑 Остановить текущую викторину"),
        BotCommand(app_config.commands.cancel, "↩️ Отменить текущее действие"),
        
        # Фото-викторина
        BotCommand("photo_quiz", "🖼️ Фото-викторина"),
        BotCommand("stop_photo_quiz", "🛑 Остановить фото-викторину"),
        BotCommand("photo_quiz_help", "ℹ️ Помощь по фото-викторине"),
        
        # Админские команды (безопасные для админов чатов)
        BotCommand(app_config.commands.admin_settings, "⚙️ Настройки бота (админ)"),
        BotCommand(app_config.commands.reset_categories_stats, "🔄 Сброс статистики категорий (админ)"),
        BotCommand(app_config.commands.chat_stats, "📊 Статистика викторин (админ)"),
        BotCommand("scheduler_status", "📅 Статус планировщика (админ)"),
    ]
    
    # Команды ТОЛЬКО для суперадминов (не показываются в меню)
    # Эти команды работают, но не отображаются в списке команд
    # Доступ к ним контролируется через проверку прав в обработчиках
    superadmin_commands = [
        # BotCommand("maintenance", "🔧 Режим обслуживания"),
        # BotCommand("backup", "💾 Создать бэкап"),
        # BotCommand("backups", "📋 Список бэкапов"),
        # BotCommand("restore", "🔄 Восстановить из бэкапа"),
        # BotCommand("deletebackup", "🗑️ Удалить бэкап"),
        # BotCommand("backupstats", "📊 Статистика бэкапов"),
    ]
    
    # Функция для установки команд с retry
    async def set_commands_with_retry(scope=None, scope_name="default", max_retries=3):
        """Устанавливает команды с повторными попытками при таймаутах"""
        for attempt in range(max_retries):
            try:
                if scope:
                    await application.bot.set_my_commands(bot_commands, scope=scope)
                else:
                    await application.bot.set_my_commands(bot_commands)
                return True
            except (TimedOut, NetworkError) as e:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2  # 2, 4, 6 секунд
                    logger.warning(
                        "Сбой при установке команд для scope=%s (попытка %s/%s), повтор через %sс: %r",
                        scope_name,
                        attempt + 1,
                        max_retries,
                        wait_time,
                        e,
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        "Не удалось установить команды для scope=%s после %s попыток: %r",
                        scope_name,
                        max_retries,
                        e,
                        exc_info=True,
                    )
                    return False
            except Exception as e:
                logger.error(
                    "Ошибка при установке команд для scope=%s: %r",
                    scope_name,
                    e,
                    exc_info=True,
                )
                return False
        return False
    
    try:
        from modules.mini_app_launch import configured_url
        try:
            mini_url = configured_url()
            if mini_url:
                from telegram import MenuButtonWebApp, WebAppInfo
                await application.bot.set_chat_menu_button(menu_button=MenuButtonWebApp('Morning Quiz', WebAppInfo(mini_url)))
        except (ValueError, TelegramError):
            logger.warning('Mini App menu was not configured; classic commands remain available')
        scope_results = [
            await set_commands_with_retry(scope_name="default"),
            await set_commands_with_retry(
                scope=BotCommandScopeAllPrivateChats(),
                scope_name="private_chats",
            ),
            await set_commands_with_retry(
                scope=BotCommandScopeAllGroupChats(),
                scope_name="group_chats",
            ),
            await set_commands_with_retry(
                scope=BotCommandScopeAllChatAdministrators(),
                scope_name="chat_admins",
            ),
        ]
        successful_scopes = sum(1 for success in scope_results if success)
        if successful_scopes == len(scope_results):
            logger.info(
                "✅ Команды бота успешно установлены для всех скоупов (%s команд).",
                len(bot_commands),
            )
        else:
            logger.warning(
                "⚠️ Команды бота установлены не для всех скоупов: %s/%s.",
                successful_scopes,
                len(scope_results),
            )
    except Exception as e_set_cmd:
        logger.error(f"❌ Не удалось установить команды бота: {e_set_cmd}", exc_info=True)
