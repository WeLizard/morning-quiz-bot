#handlers/daily_quiz_scheduler.py
from __future__ import annotations
import logging
from datetime import time, timedelta
import asyncio
from typing import TYPE_CHECKING, List, Dict, Any, Optional

import pytz
from telegram.ext import Application, ContextTypes, JobQueue

from app_config import AppConfig
from state import BotState
from data_manager import DataManager

if TYPE_CHECKING:
    from .quiz_manager import QuizManager

logger = logging.getLogger(__name__)

class DailyQuizScheduler:
    def __init__(
        self,
        app_config: AppConfig,
        state: BotState,
        data_manager: DataManager,
        quiz_manager: QuizManager,
        application: Application
    ):
        self.app_config = app_config
        self.state = state
        self.data_manager = data_manager
        self.quiz_manager = quiz_manager
        self.application = application
        self.moscow_tz = pytz.timezone('Europe/Moscow')

    def _get_job_name_for_time_entry(self, chat_id: int, time_entry_index: int) -> str:
        """Генерирует уникальное имя задачи для конкретного времени запуска в чате."""
        return f"daily_quiz_for_chat_{chat_id}_time_idx_{time_entry_index}"

    async def _trigger_daily_quiz_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.job or not isinstance(context.job.data, dict) or "chat_id" not in context.job.data:
            logger.error("_trigger_daily_quiz_job вызван без chat_id в context.job.data.")
            return

        chat_id: int = context.job.data["chat_id"]
        logger.info(f"Запуск задачи ежедневной викторины для чата {chat_id} (Job: {context.job.name if context.job else 'N/A'}).")

        active_quiz_in_chat = self.state.get_active_quiz(chat_id)
        if active_quiz_in_chat and not active_quiz_in_chat.is_stopping:
            logger.warning(f"Запуск ежедневной викторины в чате {chat_id} пропущен: другая викторина уже активна.")
            return

        if self.data_manager.postgres_storage:
            from storage.schedule_source import ScheduleSource
            from storage.schedule_plan import effective_settings
            source = ScheduleSource(self.data_manager.postgres_storage.database, self.app_config)
            snapshot = (await source.read(chat_id)).get(chat_id)
            plan = source.plan(snapshot, "quiz")
            if not plan.times or context.job.data.get("schedule_token") != plan.token:
                logger.info("Пропущена устаревшая задача квиза чата %s", chat_id)
                return
            chat_settings = effective_settings(snapshot.values, self.app_config.default_chat_settings,
                                               self.app_config.daily_quiz_defaults)
        else:
            chat_settings = await self.data_manager.get_chat_settings_async(chat_id)
        daily_quiz_cfg_chat = chat_settings.get("daily_quiz", {})
        daily_quiz_defaults_app = self.app_config.daily_quiz_defaults

        if not daily_quiz_cfg_chat.get("enabled", daily_quiz_defaults_app.get("enabled")):
            logger.info(f"Ежедневная викторина для чата {chat_id} отключена в настройках. Пропуск запуска.")
            return

        num_questions = daily_quiz_cfg_chat.get("num_questions", daily_quiz_defaults_app["num_questions"])
        open_period = daily_quiz_cfg_chat.get("poll_open_seconds", daily_quiz_defaults_app.get("poll_open_seconds", 600))
        interval_seconds = daily_quiz_cfg_chat.get("interval_seconds", daily_quiz_defaults_app["interval_seconds"])
        categories_mode = daily_quiz_cfg_chat.get("categories_mode", daily_quiz_defaults_app["categories_mode"])

        category_names_for_quiz: Optional[List[str]] = None
        is_random_categories_mode_for_quiz = False

        if categories_mode == "specific":
            category_names_for_quiz = daily_quiz_cfg_chat.get("specific_categories", daily_quiz_defaults_app.get("specific_categories", []))
            if not category_names_for_quiz:
                 logger.warning(f"Ежедневная викторина (чат {chat_id}): режим 'specific', но список категорий пуст. Будут случайные.")
                 is_random_categories_mode_for_quiz = True
        elif categories_mode == "random":
            is_random_categories_mode_for_quiz = True
        elif categories_mode == "all_enabled":
            category_names_for_quiz = None
            is_random_categories_mode_for_quiz = False

        daily_quiz_type_config_from_app = self.app_config.quiz_types_config.get("daily", {})

        await self.quiz_manager._initiate_quiz_session(
            context=context, chat_id=chat_id, initiated_by_user=None,
            quiz_type="daily",
            quiz_mode=daily_quiz_type_config_from_app.get("mode", "serial_interval"),
            num_questions=num_questions, open_period_seconds=open_period,
            announce=daily_quiz_type_config_from_app.get("announce", True),
            announce_delay_seconds=daily_quiz_type_config_from_app.get("announce_delay_seconds", 0),
            category_names_for_quiz=category_names_for_quiz,
            is_random_categories_mode=is_random_categories_mode_for_quiz,
            interval_seconds=interval_seconds
        )

    def apply_postgres_plan(self, chat_id, plan):
        """Install new jobs first; remove obsolete jobs only after all adds succeed."""
        queue = self.application.job_queue
        if queue is None:
            raise RuntimeError("JobQueue is unavailable")
        prefix = f"daily_quiz_for_chat_{chat_id}_"
        existing = [job for job in queue.jobs() if job.name and job.name.startswith(prefix) and not job.removed]
        keep, created = [], []
        try:
            for index, (hour, minute) in enumerate(plan.times):
                name = f"{prefix}pg_{plan.token}_{hour:02d}{minute:02d}"
                job = next((j for j in existing if j.name == name), None)
                if job is None:
                    job = queue.run_daily(
                        self._trigger_daily_quiz_job,
                        time=time(hour, minute, tzinfo=pytz.timezone(plan.timezone)),
                        data={"chat_id": chat_id, "time_entry_index": index, "schedule_token": plan.token},
                        name=name,
                        job_kwargs={"id": name, "replace_existing": True, "coalesce": True,
                                    "max_instances": 1, "misfire_grace_time": self.app_config.job_grace_period_seconds},
                    )
                    created.append(job)
                keep.append(job)
        except Exception:
            for job in created:
                job.schedule_removal()
            raise
        for job in existing:
            if all(job is not kept for kept in keep):
                job.schedule_removal()

    async def reschedule_job_for_chat(self, chat_id: int) -> None:
        if not self.application.job_queue:
            logger.error("JobQueue не доступен в DailyQuizScheduler. Невозможно перепланировать задачи.")
            return

        job_queue: JobQueue = self.application.job_queue # type: ignore

        # Do not remove working jobs if reading the new settings fails.
        chat_settings = await self.data_manager.get_chat_settings_async(chat_id)
        if getattr(self.data_manager, "postgres_storage", None):
            from storage.schedule_plan import build_schedule_plan
            self.apply_postgres_plan(chat_id, build_schedule_plan(chat_settings, "quiz",
                                      daily_defaults=self.app_config.daily_quiz_defaults))
            return

        prefix_job_name_base = f"daily_quiz_for_chat_{chat_id}_time_idx_"
        existing_jobs_for_chat = [job for job in job_queue.jobs() if job.name and job.name.startswith(prefix_job_name_base)]

        if existing_jobs_for_chat:
            for job in existing_jobs_for_chat:
                job.schedule_removal()
            logger.debug(f"Удалены существующие задачи ({len(existing_jobs_for_chat)}) с префиксом '{prefix_job_name_base}' для чата {chat_id} перед перепланировкой.")

        daily_quiz_cfg_chat = chat_settings.get("daily_quiz", {})
        daily_quiz_defaults_app = self.app_config.daily_quiz_defaults

        if not daily_quiz_cfg_chat.get("enabled", daily_quiz_defaults_app.get("enabled")):
            logger.info(f"Ежедневная викторина для чата {chat_id} отключена. Задачи не будут запланированы.")
            return

        # Получаем timezone из настроек чата
        chat_timezone_str = daily_quiz_cfg_chat.get("timezone", "Europe/Moscow")
        try:
            chat_timezone = pytz.timezone(chat_timezone_str)
            # Логируем timezone только если он отличается от Moscow (для новых настроек)
            if chat_timezone_str != "Europe/Moscow":
                logger.info(f"Используем часовой пояс '{chat_timezone_str}' для чата {chat_id}")
            else:
                logger.debug(f"Используем часовой пояс '{chat_timezone_str}' для чата {chat_id}")
        except pytz.exceptions.UnknownTimeZoneError:
            logger.warning(f"Неизвестный часовой пояс '{chat_timezone_str}' для чата {chat_id}, используем Moscow")
            chat_timezone = self.moscow_tz

        times_list: List[Dict[str, int]] = daily_quiz_cfg_chat.get("times_msk", daily_quiz_defaults_app.get("times_msk", []))

        if not times_list:
            logger.info(f"Для чата {chat_id} не настроено ни одного времени запуска ежедневной викторины. Задачи не запланированы.")
            return

        planned_count_for_this_chat = 0
        for i, time_entry in enumerate(times_list):
            hour_msk = time_entry.get("hour")
            minute_msk = time_entry.get("minute")

            if hour_msk is None or minute_msk is None:
                logger.warning(f"Некорректная запись времени (индекс {i}) для чата {chat_id}: {time_entry}. Пропуск.")
                continue

            job_name_for_this_time = self._get_job_name_for_time_entry(chat_id, i)

            try:
                # ИСПРАВЛЕНИЕ: Используем timezone из настроек чата вместо жестко заданного Moscow
                from datetime import datetime
                now_in_chat_tz = datetime.now(chat_timezone)
                target_datetime_chat_tz = now_in_chat_tz.replace(hour=hour_msk, minute=minute_msk, second=0, microsecond=0)

                # ОПТИМИЗАЦИЯ: Проверяем, не прошло ли уже время для сегодняшнего дня
                if target_datetime_chat_tz <= now_in_chat_tz:
                    # Время уже прошло, планируем на завтра
                    target_datetime_chat_tz = target_datetime_chat_tz + timedelta(days=1)
                    logger.debug(f"Время {hour_msk:02d}:{minute_msk:02d} уже прошло для чата {chat_id} в timezone {chat_timezone_str}, планируем на завтра")

                # Конвертируем в UTC для APScheduler
                target_datetime_utc = target_datetime_chat_tz.astimezone(pytz.UTC)
                target_time_utc = target_datetime_utc.time()

                # Для логирования создаём время в часовом поясе чата
                target_time_in_chat_tz = time(hour=hour_msk, minute=minute_msk, tzinfo=chat_timezone)

            except ValueError as e_time_format:
                logger.error(f"Некорректное время ({hour_msk}:{minute_msk}) для ежедневной викторины (индекс {i}) в чате {chat_id}: {e_time_format}. Задача не запланирована.")
                continue

            # ОПТИМИЗАЦИЯ: Проверяем, не существует ли уже такая задача
            existing_job = next((job for job in job_queue.jobs() if job.name == job_name_for_this_time), None)
            if existing_job and not existing_job.removed:
                logger.debug(f"Задача {job_name_for_this_time} уже существует и активна, пропускаем создание дубликата")
                planned_count_for_this_chat += 1
                continue

            # Логируем планируемое время для отладки
            logger.debug(f"Планируем задачу для чата {chat_id}, время {i+1}: {hour_msk:02d}:{minute_msk:02d} {chat_timezone_str} -> {target_time_utc.strftime('%H:%M')} UTC (что соответствует {target_time_in_chat_tz.strftime('%H:%M %Z')})")

            # ОПТИМИЗАЦИЯ: Добавляем минимальную паузу между созданием задач для снижения нагрузки
            if i > 0:
                await asyncio.sleep(0.1)  # ОПТИМИЗАЦИЯ: Уменьшено до 100ms пауза между задачами для одного чата
            
            job_queue.run_daily(
                callback=self._trigger_daily_quiz_job,
                time=target_time_utc,  # Время уже в UTC
                data={"chat_id": chat_id, "time_entry_index": i},
                name=job_name_for_this_time
            )
            # Для продакшена логируем только итоговую информацию, а не каждую задачу
            logger.debug(f"Ежедневная викторина для чата {chat_id} (время {i+1}) успешно запланирована на {target_time_in_chat_tz.strftime('%H:%M %Z')}. Имя задачи: {job_name_for_this_time}")
            planned_count_for_this_chat +=1

        # Логируем итоговую информацию только один раз для всех задач чата
        if planned_count_for_this_chat > 0:
            logger.info(f"Запланировано {planned_count_for_this_chat} задач ежедневной викторины для чата {chat_id}")
        elif times_list :
            logger.warning(f"Ни одна задача для ежедневной викторины не была запланирована для чата {chat_id}, хотя времена были указаны.")

    # ИЗМЕНЕНИЕ: Переименован для соответствия вызову в bot.py
    async def schedule_all_daily_quizzes_from_startup(self) -> None:
        logger.info("Инициализация задач для ежедневных викторин при запуске бота...")
        if not self.application.job_queue:
            logger.error("JobQueue не доступен при schedule_all_daily_quizzes_from_startup. Задачи не будут инициализированы.")
            return

        all_chat_ids_with_settings = list(self.state.chat_settings.keys())

        if not all_chat_ids_with_settings:
            logger.info("Нет сохраненных настроек чатов. Задачи для ежедневных викторин не инициализируются.")
            return

        # ОПТИМИЗАЦИЯ: Проверяем существующие задачи перед планированием новых
        job_queue: JobQueue = self.application.job_queue # type: ignore
        existing_daily_jobs = [job for job in job_queue.jobs() if job.name and 'daily_quiz_for_chat_' in job.name]
        
        if existing_daily_jobs:
            logger.info(f"Найдено {len(existing_daily_jobs)} существующих задач ежедневных викторин. Очищаем перед перепланированием...")
            for job in existing_daily_jobs:
                job.schedule_removal()
            # ОПТИМИЗАЦИЯ: Увеличиваем время на очистку для снижения нагрузки
            await asyncio.sleep(1.0)

        # ОПТИМИЗАЦИЯ: Ограничиваем количество одновременно планируемых задач
        max_concurrent_planning = 1  # Уменьшено до 1 для максимального снижения нагрузки
        successful_initializations = 0
        
        for i in range(0, len(all_chat_ids_with_settings), max_concurrent_planning):
            batch = all_chat_ids_with_settings[i:i + max_concurrent_planning]
            
            # Планируем задачи батчами
            for chat_id_int in batch:
                try:
                    await self.reschedule_job_for_chat(chat_id_int)
                    successful_initializations += 1
                except Exception as e:
                    logger.error(f"Ошибка при инициализации/перепланировке задач для чата {chat_id_int}: {e}", exc_info=e)
            
            # ОПТИМИЗАЦИЯ: Уменьшаем паузу между батчами для более быстрой работы
            if i + max_concurrent_planning < len(all_chat_ids_with_settings):
                await asyncio.sleep(0.3)  # ОПТИМИЗАЦИЯ: Уменьшено до 300ms пауза между батчами

        logger.info(f"Инициализация/перепланировка задач ежедневных викторин завершена. Попыток: {len(all_chat_ids_with_settings)}, успешных вызовов reschedule_job_for_chat: {successful_initializations}.")

    def get_handlers(self) -> list:
        return []

    async def adjust_timezone_for_chat(self, chat_id: int, old_timezone: str, new_timezone: str) -> bool:
        """
        Корректирует время существующих задач при смене часового пояса.
        Возвращает True если коррекция прошла успешно, False если нужна полная перепланировка.
        """
        if not self.application.job_queue:
            logger.warning(f"JobQueue не доступен для коррекции часового пояса чата {chat_id}")
            return False

        job_queue: JobQueue = self.application.job_queue # type: ignore

        # Находим все задачи для этого чата
        chat_jobs = [job for job in job_queue.jobs() if job.name and f'daily_quiz_for_chat_{chat_id}_' in job.name]

        if not chat_jobs:
            logger.debug(f"Нет активных задач для чата {chat_id}, пропускаем коррекцию часового пояса")
            return True

        try:
            # Вычисляем разницу между часовыми поясами
            old_tz = pytz.timezone(old_timezone)
            new_tz = pytz.timezone(new_timezone)
            now = datetime.now(pytz.UTC)

            # Разница в часах между поясами
            old_offset = old_tz.utcoffset(now)
            new_offset = new_tz.utcoffset(now)
            offset_diff = (new_offset - old_offset).total_seconds() / 3600

            logger.info(f"Корректировка часового пояса для чата {chat_id}: {old_timezone} -> {new_timezone} (разница: {offset_diff:+.1f} часов)")

            adjusted_count = 0
            for job in chat_jobs:
                try:
                    # Получаем текущее время задачи
                    current_time = job.trigger.run_date.time() if hasattr(job.trigger, 'run_date') else None
                    if not current_time:
                        continue

                    # Создаем datetime с текущим временем в старом поясе
                    current_datetime = datetime.combine(now.date(), current_time, old_tz)

                    # Конвертируем в новый пояс
                    new_datetime = current_datetime.astimezone(new_tz)

                    # Обновляем время задачи
                    new_time = new_datetime.time()
                    job.trigger.run_date = job.trigger.run_date.replace(hour=new_time.hour, minute=new_time.minute)

                    adjusted_count += 1
                    logger.debug(f"Задача {job.name} скорректирована: {current_time} -> {new_time}")

                except Exception as e:
                    logger.error(f"Ошибка при коррекции задачи {job.name}: {e}")

            logger.info(f"Успешно скорректировано {adjusted_count} задач для чата {chat_id}")
            return True

        except Exception as e:
            logger.error(f"Ошибка при коррекции часового пояса для чата {chat_id}: {e}")
            return False

    def get_scheduler_status(self) -> Dict[str, Any]:
        """Возвращает текущий статус планировщика ежедневных викторин"""
        if not self.application.job_queue:
            return {"error": "JobQueue не доступен"}

        job_queue: JobQueue = self.application.job_queue # type: ignore
        all_jobs = job_queue.jobs()
        daily_quiz_jobs = [job for job in all_jobs if job.name and 'daily_quiz_for_chat_' in job.name]
        
        status = {
            "total_jobs": len(all_jobs),
            "daily_quiz_jobs": len(daily_quiz_jobs),
            "scheduler_working": True,
            "daily_quiz_jobs_details": []
        }
        
        for job in daily_quiz_jobs:
            next_run = job.next_run_time
            if next_run:
                # ИСПРАВЛЕНИЕ: APScheduler планирует в UTC, конвертируем в timezone чата
                next_run_utc = next_run.replace(tzinfo=pytz.UTC)

                # Для каждого чата определяем его timezone из настроек
                chat_id_from_job = None
                for job_name_part in job.name.split('_'):
                    if job_name_part.isdigit() and len(job_name_part) > 5:  # chat_id обычно длинный
                        chat_id_from_job = int(job_name_part)
                        break

                if chat_id_from_job:
                    chat_settings = self.data_manager.get_chat_settings(chat_id_from_job)
                    chat_timezone_str = chat_settings.get("daily_quiz", {}).get("timezone", "Europe/Moscow")
                    try:
                        chat_timezone = pytz.timezone(chat_timezone_str)
                        next_run_local = next_run_utc.astimezone(chat_timezone)
                        timezone_display = chat_timezone_str
                    except:
                        chat_timezone = self.moscow_tz
                        next_run_local = next_run_utc.astimezone(chat_timezone)
                        timezone_display = "Europe/Moscow"
                else:
                    next_run_local = next_run_utc.astimezone(self.moscow_tz)
                    timezone_display = "Europe/Moscow"

                # Логируем для отладки
                logger.debug(f"Job {job.name}: next_run (UTC): {next_run_utc}, next_run_local ({timezone_display}): {next_run_local}")

                job_info = {
                    "name": job.name,
                    "next_run_utc": next_run_utc.strftime('%Y-%m-%d %H:%M:%S'),
                    "next_run_local": next_run_local.strftime('%Y-%m-%d %H:%M:%S'),
                    "timezone": timezone_display,
                    "enabled": not job.removed
                }
                status["daily_quiz_jobs_details"].append(job_info)
        
        return status

    def log_scheduler_status(self) -> None:
        """Логирует текущий статус планировщика"""
        status = self.get_scheduler_status()
        
        if "error" in status:
            logger.error(f"❌ Ошибка получения статуса планировщика: {status['error']}")
            return
        
        # Логируем текущее время сервера для отладки
        from datetime import datetime
        now_utc = datetime.now(pytz.UTC)
        now_moscow = now_utc.astimezone(self.moscow_tz)
        logger.info(f"📊 СТАТУС ПЛАНИРОВЩИКА ЕЖЕДНЕВНЫХ ВИКТОРИН:")
        logger.info(f"  Текущее время сервера UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  Текущее время сервера МСК: {now_moscow.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  Всего задач в системе: {status['total_jobs']}")
        logger.info(f"  Задач ежедневных викторин: {status['daily_quiz_jobs']}")
        logger.info(f"  Планировщик работает: {'✅ Да' if status['scheduler_working'] else '❌ Нет'}")
        
        if status['daily_quiz_jobs_details']:
            logger.info(f"  Детали задач ежедневных викторин:")
            for job_detail in status['daily_quiz_jobs_details']:
                status_icon = "✅" if job_detail['enabled'] else "❌"
                logger.info(f"    {status_icon} {job_detail['name']}")
                logger.info(f"      Следующий запуск UTC: {job_detail['next_run_utc']}")
                logger.info(f"      Следующий запуск локально ({job_detail.get('timezone', 'Europe/Moscow')}): {job_detail['next_run_local']}")
        else:
            logger.warning("  ⚠️ Нет запланированных задач ежедневных викторин")
