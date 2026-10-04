# modules/score_manager.py
import asyncio
import logging
from dataclasses import replace
import json
from pathlib import Path
import random
from typing import Dict, List, Any, Optional, Tuple, TYPE_CHECKING
from datetime import datetime, timezone, date # datetime используется для now_utc, date для ежедневного сброса
from decimal import Decimal

from telegram import User as TelegramUser

if TYPE_CHECKING:
    from app_config import AppConfig
    from state import BotState
    from data_manager import DataManager

from utils import escape_markdown_v2, pluralize, get_username_or_firstname # get_username_or_firstname используется для мотивационных сообщений

logger = logging.getLogger(__name__)

class ScoreManager:
    def __init__(self, app_config: 'AppConfig', state: 'BotState', data_manager: 'DataManager'):
        self.app_config = app_config
        self.state = state
        self.data_manager = data_manager
        self.postgres_storage = getattr(data_manager, "postgres_storage", None)
        self._member_locks = {}
        self._streak_messages = self._load_streak_messages()

    @staticmethod
    def _load_streak_messages():
        path = Path(__file__).resolve().parents[1] / "data" / "system" / "streak_achievements.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return {int(key): tuple(messages) for key, messages in
                    (value.get("streak_achievements") or {}).items() if isinstance(messages, list)}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            logger.warning("Не удалось загрузить правила достижений за серию")
            return {}

    def _classic_scoring_rules(self):
        from domain.scoring import ClassicScoringRules
        base = ClassicScoringRules.from_settings(self.app_config.global_settings)
        return replace(
            base,
            milestones=tuple(sorted(self.app_config.parsed_chat_achievements, key=abs, reverse=True)),
            streak_milestones=tuple(sorted(self._streak_messages, reverse=True)),
        )

    def _should_reset_daily_data(self, last_reset_date: Optional[str]) -> bool:
        """Проверяет, нужно ли сбросить ежедневные данные"""
        if not last_reset_date:
            return True
        
        try:
            last_reset = datetime.fromisoformat(last_reset_date).date()
            today = date.today()
            return last_reset < today
        except (ValueError, TypeError):
            return True

    def _reset_daily_data_if_needed(self, current_user_data_global: Dict[str, Any]) -> None:
        """Сбрасывает ежедневные данные если прошел день"""
        last_reset = current_user_data_global.get("last_daily_reset")
        
        if self._should_reset_daily_data(last_reset):
            # Сбрасываем ежедневные данные
            current_user_data_global["daily_answered_polls"] = set()
            current_user_data_global["last_daily_reset"] = date.today().isoformat()
            logger.info(f"Сброшены ежедневные данные для пользователя")

    async def update_score_and_get_motivation(
        self, chat_id: int, user: TelegramUser, poll_id: str, is_correct: bool,
        quiz_type_of_poll: str,
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        if not self.postgres_storage:
            return await self._update_score_in_memory(
                chat_id, user, poll_id, is_correct, quiz_type_of_poll,
            )

        from storage.members import MemberService

        # Serialize local cache publication too; the database lock coordinates
        # other bot instances and administrative edits.
        lock = self._member_locks.setdefault((chat_id, user.id), asyncio.Lock())
        async with lock:
            name = (user.first_name or "").strip() or (
                f"@{user.username}" if user.username else f"User {user.id}"
            )

            async def transition(data):
                from domain.scoring import apply_classic_score
                outcome = apply_classic_score(
                    data,
                    chat_id=chat_id,
                    user_id=user.id,
                    display_name=name,
                    answer_id=poll_id,
                    is_correct=is_correct,
                    rules=self._classic_scoring_rules(),
                )
                chat_message = private_message = streak_message = None
                if outcome.milestone is not None:
                    template = self.app_config.parsed_chat_achievements.get(outcome.milestone)
                    if template:
                        message = template.format(
                            user_name=get_username_or_firstname(user),
                            user_score=round(float(outcome.score_before), 1),
                        )
                        chat_message = private_message = escape_markdown_v2(message)
                if outcome.streak_milestone is not None:
                    choices = self._streak_messages.get(outcome.streak_milestone, ())
                    if choices:
                        message = random.choice(choices).format(
                            user_name=get_username_or_firstname(user),
                            streak=data.get("consecutive_correct", 0),
                        )
                        streak_message = escape_markdown_v2(message)
                return outcome.applied, chat_message, private_message, streak_message

            answer = await MemberService(self.postgres_storage.database).apply_answer(
                chat_id=chat_id, user_id=user.id, display_name=name,
                answer_id=poll_id, is_correct=is_correct, transition=transition,
                classic_session_id=getattr(self.state.get_active_quiz(chat_id), "session_id", None),
            )
            self.state.user_scores.setdefault(chat_id, {})[str(user.id)] = answer.data
            if not answer.applied:
                return False, None, None, None

            active_quiz = self.state.get_active_quiz(chat_id)
            if active_quiz:
                scores = active_quiz.scores.setdefault(str(user.id), {
                    "name": name, "score": 0, "correct_count": 0,
                    "answered_this_session": set(),
                })
                scores["name"] = name
                if poll_id not in scores["answered_this_session"]:
                    scores["score"] += 1 if is_correct else -0.5
                    scores["correct_count"] += int(is_correct)
                    scores["answered_this_session"].add(poll_id)
            return answer.result

    async def award_photo_answer(
        self, chat_id: int, user_id: int, answer_id: str, points: float,
    ) -> bool:
        """Award a photo answer without changing classic streak/poll counters."""
        async def transition(data):
            data["score"] = float(Decimal(str(data.get("score", 0))) + Decimal(str(points)))
            data["correct_answers_count"] = data.get("correct_answers_count", 0) + 1

        lock = self._member_locks.setdefault((chat_id, user_id), asyncio.Lock())
        async with lock:
            cached = self.state.user_scores.get(chat_id, {}).get(str(user_id), {})
            name = cached.get("name", f"User {user_id}")
            if self.postgres_storage:
                from storage.members import MemberService

                answer = await MemberService(self.postgres_storage.database).apply_answer(
                    chat_id=chat_id, user_id=user_id, display_name=None,
                    answer_id=answer_id, is_correct=True, transition=transition, kind="photo",
                )
                self.state.user_scores.setdefault(chat_id, {})[str(user_id)] = answer.data
                return answer.applied

            data = self.state.user_scores.setdefault(chat_id, {}).setdefault(str(user_id), {
                "name": name, "score": 0, "answered_polls": set(),
                "correct_answers_count": 0, "daily_answered_polls": set(),
                "first_answer_time": None, "last_answer_time": None,
                "milestones_achieved": set(),
            })
            await transition(data)
            self.data_manager.save_user_data(chat_id)
            return True

    async def _update_score_in_memory(
        self, chat_id: int, user: TelegramUser, poll_id: str, is_correct: bool,
        quiz_type_of_poll: str
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        user_id_str = str(user.id)
        chat_id_str = str(chat_id)
        
        # Проверяем корректность данных
        if chat_id == user.id:
            logger.warning(f"ВНИМАНИЕ: chat_id ({chat_id}) равен user.id ({user.id}) - это личный чат")
            # В личном чате chat_id и user.id одинаковые, это нормально

        # ИЗМЕНЕНО: Логика определения имени для state. Приоритет first_name.
        user_first_name = user.first_name
        if user_first_name and user_first_name.strip():
            user_name_for_state = user_first_name.strip()
        elif user.username:
            user_name_for_state = f"@{user.username}"
        else:
            user_name_for_state = f"User {user_id_str}"

        score_updated_in_global_state = False
        motivational_message_text: Optional[str] = None

        # Обновление очков в глобальной статистике (BotState.user_scores)
        # ИСПРАВЛЕНО: Используем правильную структуру данных
        if chat_id not in self.state.user_scores:
            self.state.user_scores[chat_id] = {}

        # Проверяем, есть ли уже данные пользователя
        if user_id_str not in self.state.user_scores[chat_id]:
            # Если пользователя нет, инициализируем с базовыми данными
            self.state.user_scores[chat_id][user_id_str] = {
                "name": user_name_for_state,
                "score": 0,
                "answered_polls": set(),  # Общая история всех ответов (для статистики)
                "correct_answers_count": 0,  # Количество правильных ответов в чате
                "daily_answered_polls": set(),  # НОВОЕ: ответы за сегодня
                "first_answer_time": None,
                "last_answer_time": None,
                "last_daily_reset": date.today().isoformat(),  # НОВОЕ: дата последнего сброса
                "milestones_achieved": set(),
                "consecutive_correct": 0,  # НОВОЕ: серия правильных ответов
                "max_consecutive_correct": 0,  # НОВОЕ: максимальная серия
                "streak_achievements_earned": set()  # НОВОЕ: полученные ачивки за серию
            }
            logger.info(f"🔍 ДЕБАГ: Создан новый пользователь {user_id_str} с полями streak_achievements_earned и daily_answered_polls")
        else:
            # Убеждаемся, что у существующего пользователя есть все необходимые поля
            current_user_data_global = self.state.user_scores[chat_id][user_id_str]
            logger.info(f"🔍 ДЕБАГ: Проверяем поля существующего пользователя {user_id_str}")
            logger.info(f"🔍 ДЕБАГ: Текущие поля: {list(current_user_data_global.keys())}")
            
            # НОВОЕ: Добавляем поля для ежедневной защиты от накрутки
            if "daily_answered_polls" not in current_user_data_global:
                current_user_data_global["daily_answered_polls"] = set()
                logger.info(f"🔍 ДЕБАГ: Добавлено поле daily_answered_polls")
            else:
                logger.info(f"🔍 ДЕБАГ: Поле daily_answered_polls уже есть: {len(current_user_data_global['daily_answered_polls'])} вопросов")
                
            if "last_daily_reset" not in current_user_data_global:
                current_user_data_global["last_daily_reset"] = date.today().isoformat()
                logger.info(f"🔍 ДЕБАГ: Добавлено поле last_daily_reset")
            else:
                logger.info(f"🔍 ДЕБАГ: Поле last_daily_reset уже есть: {current_user_data_global['last_daily_reset']}")
            
            if "streak_achievements_earned" not in current_user_data_global:
                current_user_data_global["streak_achievements_earned"] = set()
                logger.info(f"🔍 ДЕБАГ: Добавлено поле streak_achievements_earned")
            else:
                logger.info(f"🔍 ДЕБАГ: Поле streak_achievements_earned уже есть: {current_user_data_global['streak_achievements_earned']}")
                
            if "consecutive_correct" not in current_user_data_global:
                current_user_data_global["consecutive_correct"] = 0
                logger.info(f"🔍 ДЕБАГ: Добавлено поле consecutive_correct")
            else:
                logger.info(f"🔍 ДЕБАГ: Поле consecutive_correct уже есть: {current_user_data_global['consecutive_correct']}")
                
            if "max_consecutive_correct" not in current_user_data_global:
                current_user_data_global["max_consecutive_correct"] = 0
                logger.info(f"🔍 ДЕБАГ: Добавлено поле max_consecutive_correct")
            else:
                logger.info(f"🔍 ДЕБАГ: Поле max_consecutive_correct уже есть: {current_user_data_global['max_consecutive_correct']}")

            if "correct_answers_count" not in current_user_data_global:
                current_user_data_global["correct_answers_count"] = 0
                logger.info(f"🔍 ДЕБАГ: Добавлено поле correct_answers_count")
            else:
                logger.info(f"🔍 ДЕБАГ: Поле correct_answers_count уже есть: {current_user_data_global['correct_answers_count']}")

        current_user_data_global = self.state.user_scores[chat_id][user_id_str]

        # НОВОЕ: Проверяем и сбрасываем ежедневные данные если нужно
        self._reset_daily_data_if_needed(current_user_data_global)

        # JSON path, or a detached PostgreSQL transition without an active session.
        active_quiz = self.state.get_active_quiz(chat_id)
        if active_quiz:
            active_quiz.scores.setdefault(user_id_str, {"name": user_name_for_state, "score": 0, "correct_count": 0, "answered_this_session": set()})
            if active_quiz.scores[user_id_str].get("name") != user_name_for_state:
                active_quiz.scores[user_id_str]["name"] = user_name_for_state

            if (
                poll_id not in active_quiz.scores[user_id_str]["answered_this_session"]
            ):
                if is_correct:
                    active_quiz.scores[user_id_str]["score"] += 1
                    active_quiz.scores[user_id_str]["correct_count"] += 1
                else:
                    active_quiz.scores[user_id_str]["score"] -= 0.5
                active_quiz.scores[user_id_str]["answered_this_session"].add(poll_id)

        # Обновляем имя в глобальном state, если оно изменилось
        if current_user_data_global.get("name") != user_name_for_state:
            current_user_data_global["name"] = user_name_for_state
            score_updated_in_global_state = True # Считаем это обновлением, чтобы данные сохранились

        # НОВОЕ: Логика ачивок проверяется при каждом ответе, а не только при первом
        motivational_message_text = ""      # Сообщение для чата (включает streak ачивки)
        motivational_message_ls = ""        # Сообщение для лички (только чатовые ачивки, без streak)
        streak_message_text = ""            # Только streak ачивки для удаления
        name_for_motivation = get_username_or_firstname(user)
        current_score_for_motivation = current_user_data_global.get("score", 0)
        # Округляем баллы до 1 знака после запятой, как в других местах системы
        chat_score_for_motivation = round(current_score_for_motivation, 1)

        # Проверяем чатовые ачивки
        chat_achievements_config = self.app_config.parsed_chat_achievements
        sorted_chat_keys = sorted(chat_achievements_config.keys(), key=abs, reverse=True)
        found_chat_milestone = None

        for score_threshold in sorted_chat_keys:
            if score_threshold > 0 and chat_score_for_motivation >= score_threshold:
                found_chat_milestone = score_threshold
                break
            elif score_threshold < 0 and chat_score_for_motivation <= score_threshold:
                found_chat_milestone = score_threshold
                break
            elif score_threshold == 0 and chat_score_for_motivation == 0:
                found_chat_milestone = score_threshold

        # Обрабатываем чатовые ачивки
        if found_chat_milestone is not None:
            chat_milestone_id = f"chat_achievement_{chat_id_str}_{user_id_str}_{found_chat_milestone}"
            
            # Проверяем, не была ли эта чатовая ачивка уже получена в этом чате
            if chat_milestone_id not in current_user_data_global.get("milestones_achieved", set()):
                # Получаем базовое чатовое сообщение и экранируем его
                base_chat_message = chat_achievements_config[found_chat_milestone].format(
                    user_name=name_for_motivation,
                    user_score=chat_score_for_motivation
                )
                chat_message_escaped = escape_markdown_v2(base_chat_message)
                
                # Чатовые ачивки идут и в чат, и в личку (остаются навсегда)
                motivational_message_text = chat_message_escaped
                motivational_message_ls = chat_message_escaped
                
                # Добавляем чатовую ачивку только в текущий чат
                current_user_data_global.setdefault("milestones_achieved", set()).add(chat_milestone_id)
                score_updated_in_global_state = True
                logger.info(f"Пользователь {user_id_str} ({user_name_for_state}) получил ЧАТОВУЮ ачивку {found_chat_milestone} в чате {chat_id_str} ({chat_score_for_motivation} очков).")

        # Обрабатываем ачивки за серию правильных ответов
        # ПЕРЕМЕЩЕНО: Проверяем streak ачивки ПОСЛЕ обновления серии, чтобы использовать актуальное значение
        # Эта проверка будет выполнена в конце метода, после обновления consecutive_correct

        # НОВАЯ ЛОГИКА: Обновляем очки только если пользователь не отвечал на этот вопрос СЕГОДНЯ
        if (
            poll_id not in current_user_data_global.get("daily_answered_polls", set())
        ):
            # НОВАЯ ЛОГИКА: Обновляем очки с учетом бонусов за серию (В РАМКАХ ОДНОГО ЧАТА)
            current_score = current_user_data_global.get("score", 0)
            current_consecutive = current_user_data_global.get("consecutive_correct", 0)
            
            if is_correct:
                # Увеличиваем серию правильных ответов В ЭТОМ ЧАТЕ
                new_consecutive = current_consecutive + 1
                current_user_data_global["consecutive_correct"] = new_consecutive
                
                # Обновляем максимальную серию В ЭТОМ ЧАТЕ
                max_consecutive = current_user_data_global.get("max_consecutive_correct", 0)
                if new_consecutive > max_consecutive:
                    current_user_data_global["max_consecutive_correct"] = new_consecutive
                
                # Проверяем, есть ли бонус за серию
                streak_bonus_config = self.app_config.global_settings.get("streak_bonuses", {})
                if streak_bonus_config.get("enabled", False):
                    min_streak = streak_bonus_config.get("min_streak_for_bonus", 3)
                    if new_consecutive >= min_streak:
                        base_multiplier = streak_bonus_config.get("base_multiplier", 0.1)
                        max_multiplier = streak_bonus_config.get("max_multiplier", 1.0)
                        
                        # Вычисляем бонус (максимум 100%)
                        bonus_multiplier = min(new_consecutive * base_multiplier, max_multiplier)
                        score_bonus = 1 + bonus_multiplier
                        
                        current_user_data_global["score"] = current_score + score_bonus
                        logger.info(f"Пользователь {user_id_str} получил бонус за серию {new_consecutive} в чате {chat_id}: +{score_bonus:.2f} очков")
                    else:
                        current_user_data_global["score"] = current_score + 1
                else:
                    current_user_data_global["score"] = current_score + 1
            else:
                # Сбрасываем серию при неправильном ответе В ЭТОМ ЧАТЕ
                current_user_data_global["consecutive_correct"] = 0
                current_user_data_global["score"] = current_score - 0.5
                logger.info(f"Пользователь {user_id_str} сбросил серию правильных ответов в чате {chat_id}")
            
            score_updated_in_global_state = True
            
            # НОВОЕ: Увеличиваем счетчик правильных ответов если ответ правильный
            if is_correct:
                current_user_data_global["correct_answers_count"] = current_user_data_global.get("correct_answers_count", 0) + 1

            # НОВОЕ: Добавляем в ежедневные ответы (для защиты от накрутки в течение дня)
            current_user_data_global.setdefault("daily_answered_polls", set()).add(poll_id)

            # НОВОЕ: Также добавляем в общую историю (для статистики)
            current_user_data_global.setdefault("answered_polls", set()).add(poll_id)
            
            # ИСПРАВЛЕНО: Обновляем first_answer_time и last_answer_time при каждом ответе
            now_utc = datetime.now(timezone.utc)
            if current_user_data_global.get("first_answer_time") is None:
                current_user_data_global["first_answer_time"] = now_utc.isoformat()
            current_user_data_global["last_answer_time"] = now_utc.isoformat()
            
            # ОТЛАДКА: Логируем обновление
            logger.info(f"ОТЛАДКА: Пользователь {user_id_str} в чате {chat_id} ответил на опрос {poll_id}. Ежедневных ответов: {len(current_user_data_global.get('daily_answered_polls', set()))}, всего ответов: {len(current_user_data_global.get('answered_polls', set()))}")
            
            # ИСПРАВЛЕНО: Проверяем streak ачивки ПОСЛЕ обновления серии
            if is_correct:
                new_consecutive = current_user_data_global.get("consecutive_correct", 0)
                if new_consecutive > 0:
                            # Загружаем streak ачивки из системного файла
                            import random
                            import json
                            from pathlib import Path
                            
                            streak_messages = []
                            try:
                                streak_file_path = Path("data/system/streak_achievements.json")
                                if streak_file_path.exists():
                                    with open(streak_file_path, 'r', encoding='utf-8') as f:
                                        streak_data = json.load(f)
                                        # Получаем все доступные пороги из файла
                                        available_thresholds = [int(k) for k in streak_data.get("streak_achievements", {}).keys()]
                                        # Сортируем по убыванию и находим подходящий
                                        for threshold in sorted(available_thresholds, reverse=True):
                                            if new_consecutive >= threshold:
                                                streak_messages = streak_data.get("streak_achievements", {}).get(str(threshold), [])
                                                break
                            except Exception as e:
                                logger.warning(f"Не удалось загрузить streak ачивки из файла: {e}")
                            
                            # Если файл загрузился и есть сообщения
                            if streak_messages:
                                # Выбираем случайное сообщение из вариантов
                                random_message = random.choice(streak_messages)
                                streak_message = random_message.format(
                                    user_name=name_for_motivation,
                                    streak=new_consecutive
                                )
                                
                                streak_message_escaped = escape_markdown_v2(streak_message)
                                
                                # Streak ачивки добавляются в отдельное сообщение для удаления
                                if streak_message_text:
                                    streak_message_text += f"\n\n{streak_message_escaped}"
                                else:
                                    streak_message_text = streak_message_escaped
                                
                                logger.info(f"Пользователь {user_id_str} ({user_name_for_state}) получил АЧИВКУ ЗА СЕРИЮ {threshold} в чате {chat_id_str} (серия: {new_consecutive} правильных ответов подряд).")
        else:
            logger.debug(f"Пользователь {user_id_str} уже отвечал на опрос {poll_id} сегодня")
            # Не обновляем очки, но обновляем время последней активности
            now_utc = datetime.now(timezone.utc)
            if current_user_data_global.get("first_answer_time") is None:
                current_user_data_global["first_answer_time"] = now_utc.isoformat()
                score_updated_in_global_state = True  # Сохраняем, если обновили first_answer_time
            # last_answer_time обновляется всегда при любом ответе (даже повторном)
            if current_user_data_global.get("last_answer_time") != now_utc.isoformat():
                current_user_data_global["last_answer_time"] = now_utc.isoformat()
                score_updated_in_global_state = True  # Сохраняем при обновлении времени

        if score_updated_in_global_state:
            self.data_manager.save_user_data(chat_id)
            self.data_manager.update_global_statistics()

        return score_updated_in_global_state, motivational_message_text, motivational_message_ls, streak_message_text

    def get_rating_icon(self, score: int) -> str:
        if score > 0:
            if score >= 1000: return "🌟"  # Легенда
            elif score >= 500: return "🏆"  # Чемпион
            elif score >= 100: return "👑"  # Лапочка
            elif score >= 50: return "🔥"  # Огонь
            elif score >= 10: return "👍"  # Новичок с очками
            else: return "🙂"             # Мало очков (1-9)
        elif score < 0:
            return "💀"  # Отрицательный рейтинг
        else:  # player_score == 0
            return "😐"  # Нейтрально

    def format_scores(
        self,
        scores_list: List[Dict[str, Any]],
        title: str,
        is_session_score: bool = False,
        num_questions_in_session: Optional[int] = None
    ) -> str:
        logger.debug(f"format_scores вызван. Title: '{title}', is_session: {is_session_score}, num_q_sess: {num_questions_in_session}, items: {len(scores_list)}")

        # КЭШИРОВАНИЕ: Создаем ключ кэша для быстрой работы
        cache_key = f"scores_{title}_{is_session_score}_{num_questions_in_session}_{hash(str(scores_list))}"
        
        # Проверяем кэш
        if hasattr(self, '_scores_cache') and cache_key in self._scores_cache:
            logger.debug(f"Используем кэшированный рейтинг для '{title}'")
            return self._scores_cache[cache_key]

        escaped_title = escape_markdown_v2(title)
        if not scores_list:
            empty_message = "Пока нет результатов для отображения."
            if is_session_score:
                empty_message = "Никто не набрал очков в этой сессии."
            result = f"*{escaped_title}*\n\n{escape_markdown_v2(empty_message)}"
        else:
            lines = [f"*{escaped_title}*"]

            if is_session_score and num_questions_in_session is not None:
                # В сессионном счете мы показываем X/Y, поэтому счет в скобках не нужен
                # lines.append(escape_markdown_v2(f"(Всего вопросов в сессии: {num_questions_in_session})"))
                pass # Убрано для компактности и соответствия новому формату

            lines.append("") # Пустая строка для разделения

            place_icons = ["🥇", "🥈", "🥉"] # Определяем здесь, чтобы использовать ниже

            for i, entry in enumerate(scores_list):
                user_id_for_name = entry.get("user_id", "??") # Используем user_id для fallback имени
                user_name_raw = entry.get('name', f'Игрок {user_id_for_name}')
                score_val = entry.get('score', 0)

                line_parts: List[str] = []

                # 1. Место (иконка или номер)
                if i < len(place_icons) and score_val > 0: # Медали только для топ-3 с положительным счетом
                    line_parts.append(place_icons[i])
                else:
                    line_parts.append(f"{escape_markdown_v2(str(i + 1))}\\. ") # Экранируем точку и добавляем пробел

                # 2. Иконка рейтинга (эмодзи) - теперь определяется score, а не рангом
                rating_icon = self.get_rating_icon(score_val)
                line_parts.append(rating_icon)

                # 3. Имя и очки - ИЗМЕНЕНА ЛОГИКА ФОРМИРОВАНИЯ ЭТОЙ ЧАСТИ
                escaped_user_name = escape_markdown_v2(user_name_raw)

                final_name_score_segment: str
                if is_session_score and num_questions_in_session is not None:
                    # Формат для сессии: "Имя: C/Y | СТАТИСТИКА ЧАТА | <ACHIEVEMENT> T"
                    correct_val = entry.get('correct_count', entry.get('correct', None))
                    if correct_val is None:
                        # Фоллбек: если нет явного количества правильных ответов, используем max(score, 0)
                        try:
                            correct_val = int(score_val) if score_val > 0 else 0
                        except Exception:
                            correct_val = 0
                    score_display_for_session = f"{correct_val}/{num_questions_in_session}"

                    # Статистика в текущем чате
                    current_chat_score = entry.get('current_chat_score', 0)
                    current_chat_answered = entry.get('current_chat_answered', 0)

                    # Формируем строку статистики чата
                    if current_chat_answered > 0:
                        score_str = str(round(current_chat_score, 1))
                        answered_str = str(current_chat_answered)
                        chat_stats_text = f"`🏠 {escape_markdown_v2(score_str)} \\| {escape_markdown_v2(answered_str)}`"
                    else:
                        chat_stats_text = "`🏠 0.0 \\| 0`"

                    right_total_val = entry.get('global_total_score')
                    ach_icon = entry.get('achievement_icon', '⭐')
                    if not entry.get("statistics_available", True):
                        final_name_score_segment = f"{escaped_user_name}: `{escape_markdown_v2(score_display_for_session)}` · статистика временно недоступна"
                    elif right_total_val is not None:
                        # Округляем глобальные очки до 1 знака после запятой
                        rounded_global_score = round(float(right_total_val), 1)

                        # Получаем данные для нового формата
                        current_chat_answered = entry.get('current_chat_answered', 0)
                        current_chat_correct = entry.get('current_chat_correct', 0)

                        # Формируем статистику: правильные в чате / всего отвеченных в чате
                        answers_stats = f"{current_chat_correct}/{current_chat_answered}" if current_chat_answered > 0 else "0/0"

                        # Новый формат: имя + результат сессии + статистика ответов + чат + глобальный
                        # Имя обычным текстом, только числа в обратных кавычках, палочки тоже обычным текстом
                        final_name_score_segment = f"{ach_icon} {escaped_user_name}: `{escape_markdown_v2(score_display_for_session)}` \\| `{escape_markdown_v2(answers_stats)}` \\| `🏠 {escape_markdown_v2(str(round(current_chat_score, 1)))}` \\| `👑 {escape_markdown_v2(str(rounded_global_score))}`"
                    else:
                        final_name_score_segment = f"{escaped_user_name}: `{escape_markdown_v2(score_display_for_session)}` \\| {chat_stats_text}"
                else:
                    # Общий формат "Имя - X очков" (для общего рейтинга и для сессии без X/Y)
                    # Текст очков с правильным окончанием ("1 очко", "2 очка", "5 очков")
                    player_score_pluralized_text = pluralize(score_val, "очко", "очка", "очков")

                    # Определяем часть со счетом для вывода
                    score_display_part: str
                    if score_val < 0:
                        # Для отрицательного счета добавляем минус перед числом
                        # Используем абсолютное значение для текста плюрализации, но сохраняем знак для вывода
                        # Предполагаем, что pluralize(score_val) вернет текст типа "74 очка" для score_val=-74
                        score_display_part = f"- {escape_markdown_v2(player_score_pluralized_text)}" # Добавляем минус и пробел
                    else:
                        score_display_part = escape_markdown_v2(player_score_pluralized_text)

                    # Формируем конечный сегмент "Имя: `Счет`"
                    final_name_score_segment = f"{escaped_user_name}: `{score_display_part}`" # Числа в коде

                line_parts.append(final_name_score_segment)
                lines.append(" ".join(line_parts))

            result = "\n".join(lines)

        # КЭШИРОВАНИЕ: Сохраняем результат в кэш
        if not hasattr(self, '_scores_cache'):
            self._scores_cache = {}
        self._scores_cache[cache_key] = result
        
        # Ограничиваем размер кэша (храним только последние 100 результатов)
        if len(self._scores_cache) > 100:
            # Удаляем самый старый элемент
            oldest_key = next(iter(self._scores_cache))
            del self._scores_cache[oldest_key]

        return result

    async def get_chat_rating(self, chat_id: int, top_n: int = 10) -> List[Dict[str, Any]]:
        if self.postgres_storage:
            from storage.score_queries import ScoreQueries
            return await ScoreQueries(self.postgres_storage.database).rating(chat_id, top_n)
        # chat_id уже int, используем его напрямую
        if chat_id not in self.state.user_scores or not self.state.user_scores[chat_id]:
            return []

        scores_in_chat = self.state.user_scores[chat_id]
        # Сортируем по убыванию очков, затем по имени (для стабильности при равных очках)
        # data.get('name', '') or f"User {uid}" ensures name exists for sorting
        sorted_users = sorted(
            scores_in_chat.items(),
            key=lambda item: (-item[1].get("score", 0), item[1].get("name", f"User {item[0]}")),
        )

        top_users_list = []
        for i, (user_id_str, data) in enumerate(sorted_users[:top_n]):
            user_name = data.get("name", f"User {user_id_str}") # Уже должно быть подготовлено
            score = data.get("score", 0)
            # ИСПРАВЛЕНО: Округляем очки до 1 знака после запятой
            score = round(score, 1)
            try:
                user_id_int = int(user_id_str)
            except ValueError:
                user_id_int = 0 # Fallback, should not happen if user_id_str is always int
            top_users_list.append({"user_id": user_id_int, "name": user_name, "score": score})
        return top_users_list

    async def get_global_rating(self, top_n: int = 10) -> List[Dict[str, Any]]:
        if self.postgres_storage:
            from storage.score_queries import ScoreQueries
            return await ScoreQueries(self.postgres_storage.database).rating(limit=top_n)
        global_scores_agg: Dict[str, Dict[str, Any]] = {} # user_id_str -> {"name": ..., "score": ...}

        for chat_id, users_in_chat_dict in self.state.user_scores.items():
            for user_id, user_data_dict in users_in_chat_dict.items():
                user_score = user_data_dict.get("score", 0)
                user_name = user_data_dict.get("name", f"User {user_id}") # Имя уже должно быть подготовлено

                if user_id not in global_scores_agg:
                    global_scores_agg[user_id] = {"name": user_name, "score": 0}

                global_scores_agg[user_id]["score"] += user_score
                # Имя берем из первой встреченной записи; можно улучшить, если имя может меняться глобально
                # Но так как имя теперь first_name, оно должно быть консистентно для user_id
                if global_scores_agg[user_id]["name"] == f"User {user_id}" and user_name != f"User {user_id}":
                    global_scores_agg[user_id]["name"] = user_name


        sorted_global_users = sorted(
            global_scores_agg.items(),
            key=lambda item: (-item[1].get("score", 0), item[1].get("name", f"User {item[0]}")),
        )

        top_global_list = []
        for i, (user_id_str, data) in enumerate(sorted_global_users[:top_n]):
            try:
                user_id_int = int(user_id_str)
            except ValueError:
                user_id_int = 0
            score = data.get("score", 0)
            # ИСПРАВЛЕНО: Округляем очки до 1 знака после запятой
            score = round(score, 1)
            top_global_list.append({
                "user_id": user_id_int,
                "name": data.get("name", f"User {user_id_str}"),
                "score": score
            })
        return top_global_list

    async def get_user_stats_in_chat(self, chat_id: int, user_id: str) -> Optional[Dict[str, Any]]:
        if self.postgres_storage:
            return (await self.get_session_profiles(chat_id, [user_id])).get(str(user_id), {}).get("chat")
        # chat_id уже int, user_id остается str
        user_scores_chat = self.state.user_scores.get(chat_id, {}).get(user_id)
        if not user_scores_chat:
            return None

        # Возвращаем копию, чтобы избежать случайных модификаций извне
        stats = {
            "name": user_scores_chat.get("name", f"User {user_id}"),
            "score": user_scores_chat.get("score", 0),
            "answered_polls_count": len(user_scores_chat.get("answered_polls", set())), # Теперь set в state
            "first_answer_time": user_scores_chat.get("first_answer_time"),
            "last_answer_time": user_scores_chat.get("last_answer_time"),
        }
        # Удаляем сам set из возвращаемых данных, если он не нужен напрямую
        # stats.pop("answered_polls", None) # Уже не нужно, так как len берется
        # stats.pop("milestones_achieved", None) # Уже не нужно
        return stats

    async def get_global_user_stats(self, user_id: str) -> Optional[Dict[str, Any]]:
        if self.postgres_storage:
            from storage.score_queries import ScoreQueries
            return (await ScoreQueries(self.postgres_storage.database).profiles(None, [user_id])).get(str(user_id), {}).get("global")
        total_score = 0
        total_answered_polls = 0
        # Имя пользователя может отличаться в разных чатах, если логика user_name_for_state была другой.
        # С новой логикой (приоритет first_name) имя должно быть одинаковым.
        # Берем первое не-дефолтное имя.
        display_name: Optional[str] = None
        first_answer_overall: Optional[str] = None
        last_answer_overall: Optional[str] = None

        found_user_data = False
        for chat_data in self.state.user_scores.values():
            user_chat_data = chat_data.get(user_id)
            if user_chat_data:
                found_user_data = True
                total_score += user_chat_data.get("score", 0)
                answered_in_chat = user_chat_data.get("answered_polls", set())
                total_answered_polls += len(answered_in_chat) if isinstance(answered_in_chat, set) else 0

                current_name = user_chat_data.get("name")
                if display_name is None or display_name.startswith("User "): # Обновляем, если нашли более осмысленное имя
                    if current_name and not current_name.startswith("User "):
                        display_name = current_name

                # Обновление временных меток
                fat_str = user_chat_data.get("first_answer_time")
                lat_str = user_chat_data.get("last_answer_time")
                if fat_str:
                    try:
                        fat_dt = datetime.fromisoformat(fat_str)
                        if first_answer_overall is None or fat_dt < datetime.fromisoformat(first_answer_overall):
                            first_answer_overall = fat_str
                    except ValueError:
                         logger.warning(f"Неверный формат first_answer_time для пользователя {user_id} в чате: {fat_str}")

                if lat_str:
                    try:
                        lat_dt = datetime.fromisoformat(lat_str)
                        if last_answer_overall is None or lat_dt > datetime.fromisoformat(last_answer_overall):
                            last_answer_overall = lat_str
                    except ValueError:
                        logger.warning(f"Неверный формат last_answer_time для пользователя {user_id} в чате: {lat_str}")

        if not found_user_data:
            return None

        if display_name is None: # Если пользователь нигде не имел осмысленного имени
            display_name = f"User {user_id}"

        # Округляем общий счет до 1 знака после запятой
        total_score = round(total_score, 1)

        # Избегаем деления на ноль
        average_score_per_poll = (total_score / total_answered_polls) if total_answered_polls > 0 else 0.0
        # Округляем средний счет до 2 знаков после запятой
        average_score_per_poll = round(average_score_per_poll, 2)

        return {
            "name": display_name,
            "total_score": total_score,
            "answered_polls": total_answered_polls,
            "average_score_per_poll": average_score_per_poll,
            "first_answer_time_overall": first_answer_overall,
            "last_answer_time_overall": last_answer_overall,
        }

    async def get_current_chat_user_stats(self, user_id: str, chat_id: int) -> Optional[Dict[str, Any]]:
        if self.postgres_storage:
            return await self.get_user_stats_in_chat(chat_id, user_id)
        """Получает статистику пользователя только в текущем чате"""
        user_id_str = str(user_id)

        if chat_id not in self.state.user_scores:
            return None

        user_chat_data = self.state.user_scores[chat_id].get(user_id_str)
        if not user_chat_data:
            return None

        total_score = user_chat_data.get("score", 0)
        answered_polls = user_chat_data.get("answered_polls", set())
        total_answered_polls = len(answered_polls) if isinstance(answered_polls, set) else 0
        correct_answers_count = user_chat_data.get("correct_answers_count", 0)
        display_name = user_chat_data.get("name", f"User {user_id}")

        # Избегаем деления на ноль
        average_score_per_poll = (total_score / total_answered_polls) if total_answered_polls > 0 else 0.0
        average_score_per_poll = round(average_score_per_poll, 2)

        return {
            "name": display_name,
            "total_score": round(total_score, 1),
            "answered_polls": total_answered_polls,
            "correct_answers_count": correct_answers_count,
            "average_score_per_poll": average_score_per_poll,
        }

    async def get_session_profiles(self, chat_id: int, user_ids) -> Dict[str, Any]:
        if self.postgres_storage:
            from storage.score_queries import ScoreQueries
            return await ScoreQueries(self.postgres_storage.database).profiles(chat_id, user_ids)
        result = {}
        for uid in user_ids:
            chat = await self.get_current_chat_user_stats(str(uid), chat_id)
            if chat is not None:
                chat.update(await self.get_user_stats_in_chat(chat_id, str(uid)) or {})
            result[str(uid)] = {"chat": chat, "global": await self.get_global_user_stats(str(uid))}
        return result
