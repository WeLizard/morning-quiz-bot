#modules/category_manager.py
import logging
import random
import time
import json
import threading
import copy
from pathlib import Path
from typing import List, Dict, Any, Set, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from app_config import AppConfig
    from state import BotState
    from data_manager import DataManager

logger = logging.getLogger(__name__)

class CategoryManager:
    def __init__(self, state: 'BotState', app_config: 'AppConfig', data_manager: 'DataManager'):
        self.state = state
        self.app_config = app_config
        self.data_manager = data_manager
        self._postgres_storage = (
            getattr(data_manager, "postgres_storage", None)
            if getattr(app_config, "storage_backend", "postgres") == "postgres"
            else None
        )
        # Инициализируем статистику использования категорий
        self._category_usage_stats: Dict[str, Dict[str, Any]] = {}
        # Простая блокировка для защиты от race conditions при одновременных обновлениях
        self._stats_lock = threading.Lock()
        self._load_category_usage_stats()
        logger.info("CategoryManager инициализирован.")

    @property
    def _questions_by_category_from_state(self) -> Dict[str, List[Dict[str, Any]]]:
        if not hasattr(self.state, 'quiz_data') or not isinstance(self.state.quiz_data, dict):
            logger.warning("state.quiz_data отсутствует или имеет неверный тип в CategoryManager. Возвращен пустой словарь.")
            return {}
        return self.state.quiz_data

    async def refresh_postgres_statistics(self):
        if self._postgres_storage:
            from storage.models import SystemState
            async with self._postgres_storage.database.transaction() as session:
                row = await session.get(SystemState, "category_usage_stats")
                self._category_usage_stats = copy.deepcopy(row.payload if row else {})
            self.state.global_settings["category_usage_stats"] = copy.deepcopy(self._category_usage_stats)

    def _get_stats_file_path(self) -> Path:
        """Получает путь к файлу статистики категорий"""
        return self.data_manager.statistics_dir / "categories_stats.json"

    def _get_chat_stats_file_path(self, chat_id: int) -> Path:
        """Получает путь к файлу статистики категорий для конкретного чата"""
        chat_dir = self.data_manager.chats_dir / str(chat_id)
        return chat_dir / "categories_stats.json"

    def _get_total_questions_for_category(self, category_name: str) -> int:
        """Получает общее количество вопросов в категории"""
        quiz_data = self._questions_by_category_from_state
        if category_name in quiz_data:
            questions = quiz_data[category_name]
            return len(questions) if isinstance(questions, list) else 0
        return 0

    def _load_chat_category_stats(self, chat_id: int) -> Dict[str, Dict[str, Any]]:
        """Загружает статистику использования категорий для конкретного чата"""
        if self._postgres_storage:
            return {name: {"chat_usage": value.get("chat_usage", {}).get(str(chat_id), 0),
                           "last_used": value.get("last_used"),
                           "total_questions": self._get_total_questions_for_category(name)}
                    for name, value in self._category_usage_stats.items()
                    if value.get("chat_usage", {}).get(str(chat_id), 0)}
        try:
            stats_file = self._get_chat_stats_file_path(chat_id)
            if stats_file.exists():
                with open(stats_file, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                
                if loaded_data and isinstance(loaded_data, dict):
                    # Проверяем первую категорию на наличие нужных ключей
                    first_category = next(iter(loaded_data.values()), {})
                    if "chat_usage" in first_category:
                        logger.debug(f"Загружена чатовая статистика категорий для чата {chat_id}: {len(loaded_data)} записей")
                        return loaded_data
                    else:
                        logger.warning(f"Файл categories_stats.json в чате {chat_id} содержит неправильный формат. Создается новая статистика.")
                        try:
                            stats_file.unlink()
                        except Exception as e:
                            logger.warning(f"Не удалось удалить неправильный файл: {e}")
                
            return {}
        except Exception as e:
            logger.warning(f"Не удалось загрузить чатовую статистику категорий для чата {chat_id}: {e}")
            return {}

    def _save_chat_category_stats(self, chat_id: int) -> None:
        """Сохраняет статистику использования категорий для конкретного чата"""
        if self._postgres_storage:
            return
        try:
            stats_file = self._get_chat_stats_file_path(chat_id)
            # Создаем директорию, если её нет
            stats_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Подготавливаем данные для чата
            chat_stats = {}
            for category_name, stats in self._category_usage_stats.items():
                chat_id_str = str(chat_id)
                chat_usage = stats.get("chat_usage", {}).get(chat_id_str, 0)
                if chat_usage > 0:  # Сохраняем только категории, использованные в этом чате
                    # Получаем реальное количество вопросов в категории
                    total_questions_in_category = self._get_total_questions_for_category(category_name)

                    chat_stats[category_name] = {
                        "chat_usage": chat_usage,
                        "last_used": stats.get("last_used", time.time()),
                        "total_questions": total_questions_in_category
                    }
            
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(chat_stats, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"Чатовые статистики категорий для чата {chat_id} сохранены в файл")
            
        except Exception as e:
            logger.warning(f"Не удалось сохранить чатовые статистики категорий для чата {chat_id}: {e}")

    def _load_category_usage_stats(self) -> None:
        """Загружает статистику использования категорий из файла"""
        if self._postgres_storage:
            self._category_usage_stats = copy.deepcopy(
                self.state.global_settings.get("category_usage_stats", {})
            )
            self._migrate_old_category_stats_format()
            logger.info(
                "Статистика категорий загружена из PostgreSQL: %s записей",
                len(self._category_usage_stats),
            )
            return
        try:
            stats_file = self._get_stats_file_path()
            if stats_file.exists():
                with open(stats_file, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                
                # Проверяем, правильный ли это формат статистики использования
                if loaded_data and isinstance(loaded_data, dict):
                    # Проверяем первую категорию на наличие нужных ключей
                    first_category = next(iter(loaded_data.values()), {})
                    if "global_usage" in first_category or "chat_usage" in first_category:
                        # Это правильный формат статистики использования
                        self._category_usage_stats = loaded_data
                        
                        # ИСПРАВЛЕНО: Мигрируем старые данные в новый формат
                        self._migrate_old_category_stats_format()
                        
                        logger.debug(f"Загружена глобальная статистика использования категорий из файла: {len(self._category_usage_stats)} записей")
                    else:
                        # Это неправильный формат (статистика по вопросам), игнорируем
                        logger.warning("Файл categories_stats.json содержит неправильный формат (статистика по вопросам). Создается новая статистика использования.")
                        self._category_usage_stats = {}
                        # Удаляем неправильный файл
                        try:
                            stats_file.unlink()
                            logger.info("Неправильный файл categories_stats.json удален")
                        except Exception as e:
                            logger.warning(f"Не удалось удалить неправильный файл: {e}")
                else:
                    self._category_usage_stats = {}
                    logger.info("Файл categories_stats.json пуст или имеет неверный формат")
            else:
                # Если файл не существует, пытаемся загрузить из data_manager (для обратной совместимости)
                self._category_usage_stats = self.data_manager.get_global_setting("category_usage_stats", {})
                if self._category_usage_stats:
                    logger.info("Загружена статистика из data_manager (обратная совместимость)")
                    # ИСПРАВЛЕНО: Мигрируем старые данные в новый формат
                    self._migrate_old_category_stats_format()
                else:
                    self._category_usage_stats = {}
                    logger.info("Глобальная статистика категорий не найдена, создается новая")
            
            # Теперь загружаем и объединяем чатовые статистики
            self.load_all_chat_category_stats()
            
        except Exception as e:
            logger.warning(f"Не удалось загрузить глобальную статистику использования категорий: {e}")
            self._category_usage_stats = {}
            # Fallback: используем простой random.sample если что-то пошло не так
            logger.info("Используется fallback режим: простой random.sample")

    def _migrate_old_category_stats_format(self) -> None:
        """Мигрирует старые данные статистики категорий в новый формат"""
        try:
            migrated_count = 0
            
            for category_name, stats in self._category_usage_stats.items():
                # Проверяем, нужно ли мигрировать
                needs_migration = False
                
                # Проверяем отсутствие global_usage
                if "global_usage" not in stats:
                    # При миграции суммируем все chat_usage значения
                    chat_usage = stats.get("chat_usage", {})
                    if isinstance(chat_usage, dict):
                        stats["global_usage"] = sum(chat_usage.values())
                    else:
                        stats["global_usage"] = 0
                    needs_migration = True
                
                # Проверяем неправильный формат chat_usage
                chat_usage = stats.get("chat_usage", {})
                if isinstance(chat_usage, (int, float)):
                    # Старый формат: chat_usage = число
                    old_value = int(chat_usage)
                    # Создаем новый формат: chat_usage = {"chat_id": число}
                    # Определяем chat_id из chats_used_in или создаем пустой
                    chats_used = stats.get("chats_used_in", [])
                    if chats_used:
                        # Берем первый чат из списка
                        first_chat = str(chats_used[0])
                        stats["chat_usage"] = {first_chat: old_value}
                    else:
                        # Если нет чатов, создаем пустой словарь
                        stats["chat_usage"] = {}
                    needs_migration = True
                
                # Проверяем, что chat_usage является словарем
                if not isinstance(stats.get("chat_usage", {}), dict):
                    stats["chat_usage"] = {}
                    needs_migration = True
                
                if needs_migration:
                    migrated_count += 1
            
            if migrated_count > 0:
                logger.info(f"Мигрировано {migrated_count} категорий в новый формат статистики")
                # Сохраняем мигрированные данные
                self._save_category_usage_stats()
                
        except Exception as e:
            logger.warning(f"Ошибка при миграции старых данных статистики: {e}")

    def _save_category_usage_stats(self) -> None:
        """Сохраняет статистику использования категорий в файл"""
        if self._postgres_storage:
            # PG counters are written by ClassicSessions' closing transaction.
            return
        try:
            stats_file = self._get_stats_file_path()
            # Создаем директорию, если её нет
            stats_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(self._category_usage_stats, f, ensure_ascii=False, indent=2)
            
            logger.debug("Глобальная статистика использования категорий сохранена в файл")
            
            # Также сохраняем в data_manager для обратной совместимости
            self.data_manager.update_global_setting("category_usage_stats", self._category_usage_stats)
            
        except Exception as e:
            logger.warning(f"Не удалось сохранить глобальную статистику использования категорий в файл: {e}")
            # Fallback: пытаемся сохранить только в data_manager
            try:
                self.data_manager.update_global_setting("category_usage_stats", self._category_usage_stats)
                logger.debug("Статистика сохранена в data_manager (fallback)")
            except Exception as e2:
                logger.error(f"Не удалось сохранить статистику ни в файл, ни в data_manager: {e2}")


    def _update_category_usage_sync(self, category_name: str, chat_id: Optional[int] = None) -> None:
        """Простое синхронное обновление статистики с блокировкой"""
        if self._postgres_storage:
            raise RuntimeError("PG category counters are committed with session completion")
        logger.info(f"🔄 _update_category_usage_sync: Начало обновления статистики для категории '{category_name}' в чате {chat_id}")
        
        try:
            with self._stats_lock:  # Защита от race conditions
                if category_name not in self._category_usage_stats:
                    # Получаем реальное количество вопросов в категории
                    total_questions = self._get_total_questions_for_category(category_name)
                    self._category_usage_stats[category_name] = {
                        "total_questions": total_questions,
                        "last_used": time.time(),
                        "chat_usage": {},
                        "global_usage": 0,
                        "chats_used_in": []
                    }
                
                # Проверяем целостность структуры данных
                if "total_questions" not in self._category_usage_stats[category_name]:
                    total_questions = self._get_total_questions_for_category(category_name)
                    self._category_usage_stats[category_name]["total_questions"] = total_questions
                if "last_used" not in self._category_usage_stats[category_name]:
                    self._category_usage_stats[category_name]["last_used"] = time.time()
                if "chat_usage" not in self._category_usage_stats[category_name]:
                    self._category_usage_stats[category_name]["chat_usage"] = {}
                if "global_usage" not in self._category_usage_stats[category_name]:
                    self._category_usage_stats[category_name]["global_usage"] = 0
                if "chats_used_in" not in self._category_usage_stats[category_name]:
                    self._category_usage_stats[category_name]["chats_used_in"] = []
                
                # Обновляем общую статистику
                self._category_usage_stats[category_name]["last_used"] = time.time()
                self._category_usage_stats[category_name]["global_usage"] += 1

                # total_questions не должен быть в глобальной статистике
                # Он вычисляется динамически при выводе
                
                # Обновляем статистику по чатам
                if chat_id is not None:
                    chat_id_str = str(chat_id)
                    # Убеждаемся, что chat_usage является словарем
                    if not isinstance(self._category_usage_stats[category_name]["chat_usage"], dict):
                        self._category_usage_stats[category_name]["chat_usage"] = {}
                    
                    if chat_id_str not in self._category_usage_stats[category_name]["chat_usage"]:
                        self._category_usage_stats[category_name]["chat_usage"][chat_id_str] = 0
                    self._category_usage_stats[category_name]["chat_usage"][chat_id_str] += 1
                    
                    # Обновляем список чатов, где использовалась категория
                    if chat_id_str not in self._category_usage_stats[category_name]["chats_used_in"]:
                        self._category_usage_stats[category_name]["chats_used_in"].append(chat_id_str)
                    
                    # Сохраняем чатовую статистику сразу
                    self._save_chat_category_stats(chat_id)
                    logger.debug(f"💾 Сохранена чатовая статистика для чата {chat_id}")
                
                # Сохраняем глобальную статистику при каждом обновлении для актуальности
                self._save_category_usage_stats()
                logger.debug(f"💾 Сохранена глобальная статистика категории '{category_name}'")
                
                # Логируем обновление статистики
                logger.info(f"✅ Обновлена статистика категории '{category_name}': total={self._category_usage_stats[category_name]['total_questions']}, chat_{chat_id}={self._category_usage_stats[category_name]['chat_usage'].get(str(chat_id), 0) if chat_id else 'N/A'}")
                
        except Exception as e:
            logger.error(f"❌ Ошибка при обновлении статистики категории '{category_name}': {e}", exc_info=True)

    def _get_weighted_random_categories(self, candidate_pool: List[str], num_to_pick: int, chat_id: Optional[int] = None) -> List[str]:
        """Выбирает категории с учетом весов на основе частоты использования в конкретном чате"""
        candidate_pool = list(dict.fromkeys(candidate_pool))
        if not candidate_pool or num_to_pick <= 0:
            return []
        
        if len(candidate_pool) <= num_to_pick:
            return candidate_pool.copy()
        
        try:
            # Вычисляем веса для каждой категории
            category_weights = []
            current_time = time.time()
            
            for category in candidate_pool:
                if category in self._category_usage_stats:
                    stats = self._category_usage_stats[category]

                    # Проверяем целостность структуры данных
                    if "total_questions" not in stats:
                        total_questions = self._get_total_questions_for_category(category)
                        stats["total_questions"] = total_questions
                    if "last_used" not in stats:
                        stats["last_used"] = current_time
                    if "chat_usage" not in stats:
                        stats["chat_usage"] = {}

                    # Получаем число использований в этом чате
                    chat_usage = 0
                    if chat_id is not None:
                        chat_id_str = str(chat_id)
                        chat_usage_data = stats.get("chat_usage", {})
                        if not isinstance(chat_usage_data, dict):
                            chat_usage_data = {}
                        chat_usage = chat_usage_data.get(chat_id_str, 0)

                    # Исключаем категории, использованные менее 2 дней назад (для максимального разнообразия)
                    time_since_last_use = current_time - stats["last_used"]
                    days_since_use = time_since_last_use / 86400.0

                    if days_since_use < 2.0:
                        # Пропускаем недавно использованные категории
                        logger.debug(f"Категория '{category}' пропущена: использовалась {days_since_use:.1f} дней назад")
                        continue

                    # СТРАТЕГИЯ МАКСИМАЛЬНОГО РАЗНООБРАЗИЯ:
                    # Вес обратно пропорционален числу использований в чате
                    if chat_usage == 0:
                        # Новая категория для этого чата - максимальный приоритет
                        final_weight = 100.0
                    else:
                        # Чем меньше использований, тем выше вес
                        final_weight = 100.0 / chat_usage

                    # Линейный бонус за давность (+2 балла за каждый день)
                    final_weight += days_since_use * 2.0

                    category_weights.append((category, final_weight))
                    logger.debug(f"Категория '{category}': usage={chat_usage}, days={days_since_use:.1f}, weight={final_weight:.2f}")
                else:
                    # Категории, которых нет в статистике, получают максимальный приоритет
                    category_weights.append((category, 100.0))
                    logger.debug(f"Категория '{category}': новая, weight=100.0")
            
            # Сортируем по весам (по убыванию)
            category_weights.sort(key=lambda x: x[1], reverse=True)
            
            # Выбираем top категории, но добавляем элемент случайности
            top_categories = category_weights[:min(num_to_pick * 2, len(category_weights))]
            
            # Перемешиваем top категории для добавления случайности
            random.shuffle(top_categories)
            
            # Возвращаем нужное количество
            selected_categories = [cat for cat, _ in top_categories[:num_to_pick]]
            # Cooldown is a preference, not a reason to silently shrink a quiz.
            # Retain all eligible picks; fill a shortage from the remaining pool.
            if len(selected_categories) < num_to_pick:
                remaining = [cat for cat in candidate_pool if cat not in selected_categories]
                selected_categories.extend(random.sample(remaining, num_to_pick - len(selected_categories)))
            
            logger.debug(f"Выбрано {len(selected_categories)} категорий с весами: {[(cat, weight) for cat, weight in category_weights[:num_to_pick]]}")
            return selected_categories
            
        except Exception as e:
            # Fallback: если что-то пошло не так, используем простой random.sample
            logger.warning(f"Ошибка в системе весов категорий, используется fallback: {e}")
            return random.sample(candidate_pool, num_to_pick)



    def get_category_weights_for_chat(self, chat_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Получает веса всех категорий для конкретного чата для отображения очереди"""
        quiz_data = self._questions_by_category_from_state
        if not quiz_data:
            return []

        try:
            category_weights = []
            current_time = time.time()

            for category_name in quiz_data.keys():
                if category_name in self._category_usage_stats:
                    stats = self._category_usage_stats[category_name]

                    # Проверяем целостность структуры данных
                    if "total_questions" not in stats:
                        total_questions = self._get_total_questions_for_category(category_name)
                        stats["total_questions"] = total_questions
                    if "last_used" not in stats:
                        stats["last_used"] = current_time
                    if "chat_usage" not in stats:
                        stats["chat_usage"] = {}

                    # Получаем число использований в этом чате
                    chat_usage = 0
                    if chat_id is not None:
                        chat_id_str = str(chat_id)
                        chat_usage_data = stats.get("chat_usage", {})
                        if not isinstance(chat_usage_data, dict):
                            chat_usage_data = {}
                        chat_usage = chat_usage_data.get(chat_id_str, 0)

                    # Время с последнего использования
                    time_since_last_use = current_time - stats["last_used"]
                    days_since_use = time_since_last_use / 86400.0

                    # СТРАТЕГИЯ МАКСИМАЛЬНОГО РАЗНООБРАЗИЯ (та же, что в _get_weighted_random_categories)
                    # Вес обратно пропорционален числу использований
                    if chat_usage == 0:
                        final_weight = 100.0
                    else:
                        final_weight = 100.0 / chat_usage

                    # Линейный бонус за давность (+2 балла за каждый день)
                    time_bonus = days_since_use * 2.0
                    final_weight += time_bonus

                    # Отмечаем исключённые категории (использованные менее 2 дней назад)
                    excluded = days_since_use < 2.0

                    # Получаем количество вопросов
                    question_count = self._get_total_questions_for_category(category_name)

                    # Форматируем время последнего использования
                    last_used_str = "никогда"
                    if stats["last_used"] > 0:
                        days_ago = int(days_since_use)
                        if days_ago == 0:
                            last_used_str = "сегодня"
                        elif days_ago == 1:
                            last_used_str = "вчера"
                        else:
                            last_used_str = f"{days_ago} дней назад"

                    category_info = {
                        "name": category_name,
                        "weight": final_weight,
                        "time_bonus": time_bonus,
                        "chat_usage": chat_usage,
                        "question_count": question_count,
                        "last_used": last_used_str,
                        "excluded": excluded,
                        "days_since_use": days_since_use
                    }

                else:
                    # Категории, которых нет в статистике - максимальный приоритет
                    question_count = self._get_total_questions_for_category(category_name)
                    category_info = {
                        "name": category_name,
                        "weight": 100.0,
                        "time_bonus": 0.0,
                        "chat_usage": 0,
                        "question_count": question_count,
                        "last_used": "никогда",
                        "excluded": False,
                        "days_since_use": float('inf')
                    }

                category_weights.append(category_info)

            # Сортируем по весу (по убыванию - самые приоритетные сверху)
            category_weights.sort(key=lambda x: x["weight"], reverse=True)

            return category_weights

        except Exception as e:
            logger.error(f"Ошибка при расчете весов категорий для чата {chat_id}: {e}")
            return []

    def get_all_category_names(self, with_question_counts: bool = False, chat_id: Optional[int] = None) -> Union[List[str], List[Dict[str, Any]]]:
        quiz_data = self._questions_by_category_from_state
        if not quiz_data:
            return []

        if with_question_counts:
            result = []
            for name, qs in quiz_data.items():
                if qs:
                    category_info = {"name": name, "count": len(qs)}
                    
                    # Добавляем статистику использования в чате, если указан chat_id
                    if chat_id is not None and name in self._category_usage_stats:
                        chat_id_str = str(chat_id)
                        # Убеждаемся, что chat_usage является словарем
                        chat_usage_data = self._category_usage_stats[name].get("chat_usage", {})
                        if not isinstance(chat_usage_data, dict):
                            chat_usage_data = {}
                        chat_usage = chat_usage_data.get(chat_id_str, 0)
                        category_info["chat_usage"] = chat_usage
                    
                    # Добавляем глобальную статистику
                    if name in self._category_usage_stats:
                        # global_usage - сумма использований по всем чатам
                        global_usage = self._category_usage_stats[name].get("global_usage", 0)
                        category_info["global_usage"] = global_usage
                        # total_questions - берем из количества вопросов в категории
                        total_questions = len(quiz_data.get(name, []))
                        category_info["total_questions"] = total_questions
                    
                    result.append(category_info)
            return result
        else:
            return [name for name, qs in quiz_data.items() if qs]

    def get_questions(
        self,
        num_questions_needed: int,
        chat_id: Optional[int] = None,
        allowed_specific_categories: Optional[List[str]] = None,
        mode: str = "random_from_pool"
    ) -> List[Dict[str, Any]]:

        if chat_id is not None:
            chat_settings = self.data_manager.get_chat_settings(chat_id)
        else:
            chat_settings = self.app_config.default_chat_settings

        chat_enabled_cats_setting: Optional[List[str]] = chat_settings.get("enabled_categories")
        chat_disabled_cats_setting: Set[str] = set(chat_settings.get("disabled_categories", []))
        
        # НОВОЕ: Получаем настройки пула категорий для /quiz ИЗ НОВОЙ СТРУКТУРЫ
        from modules.quiz_preferences import category_preferences
        quiz_categories_mode, quiz_categories_pool, category_count = category_preferences(chat_settings)

        all_system_category_names_with_questions = [
            name for name, questions in self._questions_by_category_from_state.items() if questions
        ]

        source_categories_names: List[str] = []

        if mode == "specific_only":
            if not allowed_specific_categories:
                logger.warning("get_questions: режим 'specific_only' вызван без 'allowed_specific_categories'.")
                return []
            source_categories_names = [
                cat_name for cat_name in allowed_specific_categories
                if cat_name in all_system_category_names_with_questions and cat_name not in chat_disabled_cats_setting
            ]
        elif mode == "random_from_pool":
            # НОВАЯ ЛОГИКА: Применяем настройки пула категорий для /quiz
            candidate_pool_for_random: List[str]
            
            if quiz_categories_mode == "specific":
                # Режим "specific": только указанные категории
                candidate_pool_for_random = [
                    cat_name for cat_name in quiz_categories_pool
                    if cat_name in all_system_category_names_with_questions and cat_name not in chat_disabled_cats_setting
                ]
            elif quiz_categories_mode == "exclude":
                candidate_pool_for_random = [name for name in all_system_category_names_with_questions
                    if name not in chat_disabled_cats_setting and name not in quiz_categories_pool]
            elif quiz_categories_mode == "random":
                # Режим "random": случайные категории из всех доступных
                candidate_pool_for_random = [
                    cat_name for cat_name in all_system_category_names_with_questions
                    if cat_name not in chat_disabled_cats_setting
                ]
            else:
                # Режим "all": все доступные категории
                candidate_pool_for_random = [
                    cat_name for cat_name in all_system_category_names_with_questions
                    if cat_name not in chat_disabled_cats_setting
                ]
            
            # Применяем фильтры чата
            if chat_enabled_cats_setting:
                candidate_pool_for_random = [
                    cat_name for cat_name in candidate_pool_for_random
                    if cat_name in chat_enabled_cats_setting
                ]
            
            # Выбираем категории с учетом весов
            source_categories_names = self._get_weighted_random_categories(
                candidate_pool_for_random, 
                category_count,
                chat_id
            )
        else:
            # Fallback: все доступные категории
            source_categories_names = [
                cat_name for cat_name in all_system_category_names_with_questions
                if cat_name not in chat_disabled_cats_setting
            ]

        if not source_categories_names:
            logger.warning("get_questions: не найдено подходящих категорий для выбора вопросов.")
            return []

        # НЕ обновляем статистику здесь - это делается при старте викторины в quiz_manager.py
        # Статистика должна увеличиваться только при запуске викторины, а не при выборе вопросов

        # Собираем вопросы из выбранных категорий
        all_questions: List[Dict[str, Any]] = []
        for category_name in source_categories_names:
            if category_name in self._questions_by_category_from_state:
                category_questions = self._questions_by_category_from_state[category_name]
                # Добавляем поле current_category_name_for_quiz для каждого вопроса
                for question in category_questions:
                    question_copy = question.copy()
                    question_copy['current_category_name_for_quiz'] = category_name
                    all_questions.append(question_copy)

        if not all_questions:
            logger.warning("get_questions: не найдено вопросов в выбранных категориях.")
            return []

        # Перемешиваем вопросы и возвращаем нужное количество
        random.shuffle(all_questions)
        return all_questions[:num_questions_needed]

    def is_valid_category(self, category_name: str) -> bool:
        quiz_data = self._questions_by_category_from_state
        return category_name in quiz_data and bool(quiz_data[category_name])

    def get_category_usage_stats(self, category_name: Optional[str] = None, read_only: bool = True) -> Dict[str, Any]:
        """Получает статистику использования категорий (синхронно)"""
        with self._stats_lock:
            if category_name:
                return self._category_usage_stats.get(category_name, {}).copy()
            else:
                return self._category_usage_stats.copy()
    
    def get_category_usage_stats_sync(self, category_name: Optional[str] = None, read_only: bool = True) -> Dict[str, Any]:
        """Синхронная версия для обратной совместимости"""
        # Просто вызываем основной метод
        return self.get_category_usage_stats(category_name, read_only)

    def reset_category_usage_stats(self, category_name: Optional[str] = None) -> None:
        """Сбрасывает статистику использования категорий"""
        if self._postgres_storage:
            raise RuntimeError("Сброс статистики PostgreSQL пока не поддерживается")
        if category_name and category_name in self._category_usage_stats:
            del self._category_usage_stats[category_name]
        else:
            self._category_usage_stats.clear()
        
        self._save_category_usage_stats()

    def force_save_all_stats(self) -> None:
        """Принудительно сохраняет все статистики категорий (глобальную и чатовые)"""
        try:
            # Сохраняем глобальную статистику
            self._save_category_usage_stats()
            
            # Сохраняем чатовые статистики для всех чатов
            if hasattr(self.data_manager, 'chats_dir') and self.data_manager.chats_dir.exists():
                for chat_dir in self.data_manager.chats_dir.iterdir():
                    if chat_dir.is_dir() and (chat_dir.name.startswith('-') or chat_dir.name.isdigit()):
                        try:
                            chat_id = int(chat_dir.name)
                            self._save_chat_category_stats(chat_id)
                        except (ValueError, Exception) as e:
                            logger.debug(f"Пропускаем сохранение для чата {chat_dir.name}: {e}")
                            continue
            
            logger.info("Все статистики категорий принудительно сохранены")
            
        except Exception as e:
            logger.error(f"Ошибка при принудительном сохранении всех статистик: {e}")

    def get_chat_category_stats(self, chat_id: int) -> Dict[str, Dict[str, Any]]:
        """Получает статистику использования категорий для конкретного чата"""
        try:
            return self._load_chat_category_stats(chat_id)
        except Exception as e:
            logger.warning(f"Не удалось получить чатовую статистику категорий для чата {chat_id}: {e}")
            return {}

    def get_global_category_stats(self) -> Dict[str, Dict[str, Any]]:
        """Получает глобальную статистику использования категорий"""
        return self._category_usage_stats.copy()

    def force_save_stats(self) -> None:
        """Принудительно сохраняет статистику в файл"""
        self._save_category_usage_stats()
        logger.info("Статистика категорий принудительно сохранена")

    def load_all_chat_category_stats(self) -> None:
        """Загружает статистику категорий из всех чатов и объединяет с глобальной"""
        try:
            # Получаем список всех чатов
            chats_dir = self.data_manager.chats_dir
            if not chats_dir.exists():
                logger.debug("Директория чатов не существует, пропускаем загрузку чатовых статистик")
                return
            
            for chat_dir in chats_dir.iterdir():
                if chat_dir.is_dir() and (chat_dir.name.startswith('-') or chat_dir.name.isdigit()):
                    try:
                        chat_id = int(chat_dir.name)
                        chat_stats = self._load_chat_category_stats(chat_id)
                        
                        # Объединяем с глобальной статистикой
                        for category_name, chat_data in chat_stats.items():
                            if category_name not in self._category_usage_stats:
                                self._category_usage_stats[category_name] = {
                                    "total_questions": 0,
                                    "last_used": chat_data.get("last_used", time.time()),
                                    "chat_usage": {},
                                    "global_usage": 0
                                }
                            
                            # ИСПРАВЛЕНО: Обрабатываем разные форматы chat_usage
                            chat_id_str = str(chat_id)
                            chat_usage_value = chat_data.get("chat_usage", 0)
                            
                            # Проверяем формат chat_usage
                            if isinstance(chat_usage_value, dict):
                                # Новый формат: {"chat_id": usage_count}
                                usage_count = chat_usage_value.get(chat_id_str, 0)
                            elif isinstance(chat_usage_value, (int, float)):
                                # Старый формат: просто число
                                usage_count = int(chat_usage_value)
                            else:
                                # Неизвестный формат, пропускаем
                                logger.warning(f"Неизвестный формат chat_usage для категории {category_name} в чате {chat_id}: {chat_usage_value}")
                                continue
                            
                            # Обновляем чатовую статистику
                            self._category_usage_stats[category_name]["chat_usage"][chat_id_str] = usage_count
                            
                            # Обновляем глобальную статистику (сумма всех chat_usage)
                            all_chat_usage = list(self._category_usage_stats[category_name]["chat_usage"].values())
                            self._category_usage_stats[category_name]["global_usage"] = sum(all_chat_usage)

                            # total_questions из чатового файла можно использовать для проверки
                            # но не сохраняется в глобальную статистику
                            
                    except (ValueError, Exception) as e:
                        logger.debug(f"Пропускаем директорию {chat_dir.name}: {e}")
                        continue
            
            logger.info(f"Загружены чатовые статистики категорий и объединены с глобальной")
            
        except Exception as e:
            logger.warning(f"Ошибка при загрузке чатовых статистик категорий: {e}")
