#handlers/wisdom_scheduler.py
from __future__ import annotations
import logging
import asyncio
import json
import random
from datetime import datetime, time
from typing import TYPE_CHECKING, Dict, List, Optional, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor

from telegram.constants import ParseMode
from telegram.error import BadRequest

from utils import escape_markdown_v2

if TYPE_CHECKING:
    from app_config import AppConfig
    from data_manager import DataManager
    from state import BotState

logger = logging.getLogger(__name__)

# Импортируем OpenRouter клиент для генерации фактов
try:
    from modules.openrouter_client import get_openrouter_client
    OPENROUTER_AVAILABLE = True
except ImportError:
    OPENROUTER_AVAILABLE = False
    logger.debug("OpenRouter клиент недоступен")

class WisdomScheduler:
    """Планировщик ежедневной отправки мудрости дня"""

    def __init__(self, app_config: AppConfig, data_manager: DataManager, bot_state: BotState, application=None, category_manager=None):
        logger.debug("WisdomScheduler.__init__ начат.")
        self.app_config = app_config
        self.data_manager = data_manager
        self.bot_state = bot_state
        self.application = application
        self.category_manager = category_manager  # Для получения списка категорий

        # Инициализируем планировщик
        self.scheduler = AsyncIOScheduler(
            jobstores={'default': MemoryJobStore()},
            executors={'default': AsyncIOExecutor()},
            job_defaults={'misfire_grace_time': self.app_config.job_grace_period_seconds},
            timezone='UTC'
        )

        # Храним отправленные мудрости для каждого чата, чтобы избежать повторений
        self.sent_wisdoms: Dict[str, List[str]] = {}

        # Загружаем мудрости
        self.wisdoms = self._load_wisdoms()
        
        # Инициализируем OpenRouter клиент для генерации фактов
        self.openrouter_client = None
        if OPENROUTER_AVAILABLE and not getattr(app_config, 'disable_external_ai', False):
            self.openrouter_client = get_openrouter_client()
            if self.openrouter_client and self.openrouter_client.api_key:
                logger.info("✅ OpenRouter доступен для генерации фактов Совы Филиныча")
            else:
                logger.debug("OpenRouter API ключ не установлен, будут использоваться только статичные мудрости")

        logger.debug(f"WisdomScheduler.__init__ завершен. Загружено {len(self.wisdoms)} мудростей.")

    def _load_wisdoms(self) -> List[str]:
        """Загружает мудрости из файла"""
        try:
            wisdom_file = self.app_config.paths.data_dir / "media" / "fake_wisdom.json"
            if wisdom_file.exists():
                with open(wisdom_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return [item['message'] for item in data if isinstance(item, dict) and 'message' in item]
            else:
                logger.warning(f"Файл мудростей не найден: {wisdom_file}")
                return []
        except Exception as e:
            logger.error(f"Ошибка при загрузке мудростей: {e}")
            return []

    def _get_random_wisdom(self, chat_id: str) -> Optional[str]:
        """Получает случайную мудрость, стараясь избежать повторений"""
        if not self.wisdoms:
            return None

        chat_key = str(chat_id)
        if chat_key not in self.sent_wisdoms:
            self.sent_wisdoms[chat_key] = []

        # Получаем список доступных мудростей (исключая недавно отправленные)
        available_wisdoms = [w for w in self.wisdoms if w not in self.sent_wisdoms[chat_key]]

        # Если все мудрости уже отправлялись, сбрасываем историю
        if not available_wisdoms:
            self.sent_wisdoms[chat_key] = []
            available_wisdoms = self.wisdoms.copy()

        # Выбираем случайную мудрость
        selected_wisdom = random.choice(available_wisdoms)

        # Добавляем в историю отправленных (храним последние 50 для каждого чата)
        self.sent_wisdoms[chat_key].append(selected_wisdom)
        if len(self.sent_wisdoms[chat_key]) > 50:
            self.sent_wisdoms[chat_key].pop(0)

        return selected_wisdom

    async def _send_daily_wisdom(self, chat_id: str, context=None, schedule_token=None) -> None:
        """Отправляет мудрость дня или занимательный факт от Совы Филиныча в указанный чат"""
        try:
            logger.debug(f"Отправка мудрости/факта в чат {chat_id}")
            source = None
            if self.data_manager.postgres_storage:
                from storage.schedule_source import ScheduleSource
                source = ScheduleSource(self.data_manager.postgres_storage.database, self.app_config)
                if not await source.is_current(chat_id, "wisdom", schedule_token):
                    return

            # Случайно выбираем тип контента: True - факт от AI, False - старая мудрость
            use_ai_fact = random.choice([True, False])
            
            fact_text = None
            # Если выбран факт от AI, пытаемся сгенерировать
            if use_ai_fact and self.openrouter_client and self.openrouter_client.client:
                try:
                    # Получаем список категорий для использования как тем
                    categories = None
                    if self.category_manager:
                        try:
                            categories = self.category_manager.get_all_category_names()
                            if not categories:
                                categories = None
                        except Exception as e:
                            logger.debug(f"Не удалось получить категории для факта: {e}")
                    
                    fact_text = await self.openrouter_client.generate_fun_fact(categories=categories)
                    if fact_text:
                        logger.info(f"✅ Сгенерирован факт от Совы Филиныча для чата {chat_id}")
                except Exception as e:
                    logger.warning(f"Ошибка генерации факта через OpenRouter: {e}, используем статичную мудрость")
            
            # Если факт не удалось сгенерировать (или изначально выбрана старая мудрость), используем статичную мудрость
            if not fact_text:
                wisdom = self._get_random_wisdom(chat_id)
                if not wisdom:
                    logger.warning(f"Нет доступных мудростей для чата {chat_id}")
                    return
                
                # Формируем сообщение со старой мудростью
                message_text = f"🧠 Мудрость дня:\n\n{escape_markdown_v2(wisdom)}"
            else:
                # Формируем сообщение с фактом от Совы Филиныча
                message_text = f"🦉 *Сов Филиныч рассказывает:*\n\n{escape_markdown_v2(fact_text)}"

            # Отправляем сообщение
            if source and not await source.is_current(chat_id, "wisdom", schedule_token):
                return  # The schedule may have changed during content generation.
            if self.application:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message_text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                    disable_notification=False  # Уведомление включено
                )
            else:
                logger.error(f"Application не доступен для отправки в чат {chat_id}")

            logger.info(f"Мудрость/факт отправлен в чат {chat_id}")

        except BadRequest as e:
            logger.error(f"Ошибка при отправке мудрости/факта в чат {chat_id}: {e}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при отправке мудрости/факта в чат {chat_id}: {e}")

    def apply_postgres_plan(self, chat_id, plan):
        legacy = f"wisdom_{chat_id}"
        prefix = f"{legacy}_pg_"
        existing = [j for j in self.scheduler.get_jobs() if j.id == legacy or j.id.startswith(prefix)]
        keep, created = set(), []
        try:
            for hour, minute in plan.times:
                job_id = f"{prefix}{plan.token}_{hour:02d}{minute:02d}"
                if not any(j.id == job_id for j in existing):
                    self.scheduler.add_job(
                        self._send_daily_wisdom,
                        trigger=CronTrigger(hour=hour, minute=minute, timezone=plan.timezone),
                        args=[str(chat_id)], kwargs={"schedule_token": plan.token},
                        id=job_id, name=f"Мудрость дня для чата {chat_id}", replace_existing=True,
                        coalesce=True, max_instances=1,
                        misfire_grace_time=self.app_config.job_grace_period_seconds,
                    )
                    created.append(job_id)
                keep.add(job_id)
        except Exception:
            for job_id in created:
                self.scheduler.remove_job(job_id)
            raise
        for job in existing:
            if job.id not in keep:
                self.scheduler.remove_job(job.id)

    def schedule_wisdom_for_chat(self, chat_id: str, wisdom_time: str, timezone_str: str) -> bool:
        """Планирует отправку мудрости дня для конкретного чата"""
        try:
            logger.debug(f"Планирование мудрости дня для чата {chat_id} в {wisdom_time} ({timezone_str})")

            # Парсим время
            hour, minute = map(int, wisdom_time.split(':'))

            # Создаем триггер
            trigger = CronTrigger(
                hour=hour,
                minute=minute,
                timezone=timezone_str
            )

            # Удаляем старую задачу для этого чата, если она есть
            job_id = f"wisdom_{chat_id}"
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logger.debug(f"Удалена старая задача мудрости дня для чата {chat_id}")

            # Добавляем новую задачу
            self.scheduler.add_job(
                self._send_daily_wisdom,
                trigger=trigger,
                args=[chat_id],
                id=job_id,
                name=f"Мудрость дня для чата {chat_id}",
                replace_existing=True
            )

            logger.info(f"Запланирована мудрость дня для чата {chat_id} в {wisdom_time} ({timezone_str})")
            return True

        except Exception as e:
            logger.error(f"Ошибка при планировании мудрости дня для чата {chat_id}: {e}")
            return False

    def unschedule_wisdom_for_chat(self, chat_id: str) -> bool:
        """Отменяет планирование мудрости дня для конкретного чата"""
        try:
            job_id = f"wisdom_{chat_id}"
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logger.info(f"Отменено планирование мудрости дня для чата {chat_id}")
                return True
            else:
                logger.debug(f"Задача мудрости дня для чата {chat_id} не найдена")
                return False
        except Exception as e:
            logger.error(f"Ошибка при отмене планирования мудрости дня для чата {chat_id}: {e}")
            return False

    def get_scheduled_wisdoms(self) -> List[Dict[str, Any]]:
        """Возвращает список всех запланированных мудростей дня"""
        jobs = []
        for job in self.scheduler.get_jobs():
            if job.id.startswith("wisdom_"):
                chat_id = job.id.replace("wisdom_", "")
                trigger = job.trigger

                jobs.append({
                    'chat_id': chat_id,
                    'next_run': trigger.get_next_fire_time(None),
                    'trigger': str(trigger)
                })

        return jobs

    def start(self) -> None:
        """Запускает планировщик"""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Планировщик мудрости дня запущен")

    def shutdown(self) -> None:
        """Останавливает планировщик"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Планировщик мудрости дня остановлен")

    def reload_wisdoms(self) -> None:
        """Перезагружает список мудростей"""
        old_count = len(self.wisdoms)
        self.wisdoms = self._load_wisdoms()
        logger.info(f"Мудрости перезагружены: {old_count} → {len(self.wisdoms)}")

    def schedule_all_wisdoms_from_startup(self) -> None:
        """Планирует мудрость дня для всех чатов при запуске бота"""
        logger.info("Инициализация задач мудрости дня при запуске бота...")

        all_chat_ids_with_settings = list(self.bot_state.chat_settings.keys())

        if not all_chat_ids_with_settings:
            logger.info("Нет сохраненных настроек чатов. Задачи мудрости дня не инициализируются.")
            return

        scheduled_count = 0
        for chat_id_str in all_chat_ids_with_settings:
            try:
                chat_id = int(chat_id_str)
                settings = self.data_manager.get_chat_settings(chat_id)
                wisdom_settings = settings.get('daily_wisdom', {})

                if wisdom_settings.get('enabled', False):
                    wisdom_time = wisdom_settings.get('time', '09:00')
                    # Используем часовой пояс от ежедневной викторины
                    wisdom_timezone = settings.get('daily_quiz', {}).get('timezone', 'Europe/Moscow')

                    if self.schedule_wisdom_for_chat(chat_id, wisdom_time, wisdom_timezone):
                        scheduled_count += 1
                        logger.debug(f"Запланирована мудрость дня для чата {chat_id}")

            except Exception as e:
                logger.error(f"Ошибка при планировании мудрости дня для чата {chat_id_str}: {e}")

        logger.info(f"Запланировано мудрость дня для {scheduled_count} чатов из {len(all_chat_ids_with_settings)}")
