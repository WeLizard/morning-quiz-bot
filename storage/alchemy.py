"""Серверные механики «Алхимии»: прогресс, очки и внутриигровые достижения.

Клиент присылает только собственное локальное состояние, поэтому открытые
элементы, закрытые главы и достижения пересчитываются здесь по каталогу
`minigames/alchemia-1.0/data.json`. Файл большой (276 КБ), поэтому читается
один раз на процесс.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .database import Database
from .models import Account, AlchemyCraftCommand, AlchemyProgress, User
from .guest_accounts import GuestAccounts
from .mini_app import MiniAppError
from .repositories import OperationalRepository

logger = logging.getLogger(__name__)

CATALOG_PATH = Path(__file__).resolve().parents[1] / 'minigames' / 'alchemia-1.0' / 'data.json'
MOSCOW = ZoneInfo('Europe/Moscow')

POINTS_PER_ELEMENT = Decimal('2')
POINTS_PER_CHAPTER = Decimal('3')
POINTS_PER_ACHIEVEMENT = Decimal('5')
DAILY_POINTS_LIMIT = Decimal('30')
# Цель дня: сколько очков достаточно, чтобы день считался закрытым. Награда за неё —
# не дополнительные очки (их отсекает суточный потолок), а серия дней и понимание,
# сколько ещё можно набрать сегодня.
DAILY_GOAL_POINTS = Decimal('10')
ACHIEVEMENT_CODE_PREFIX = 'alchemy_'
MAX_LEADERBOARD_LIMIT = 100

ACHIEVEMENT_TYPES = ('count', 'elements', 'tried', 'recipes')
BASE_ELEMENTS = frozenset({'water', 'earth', 'fire', 'air'})


@dataclass(frozen=True)
class AlchemyCatalog:
    """Неизменяемый срез контента игры, прочитанный из data.json."""

    element_ids: frozenset[str]
    recipe_keys: frozenset[str]
    recipes: dict[str, tuple[str, str, str]]
    chapters: tuple[tuple[str, frozenset[str]], ...]
    achievements: tuple[dict[str, Any], ...]

    def recipe(self, ingredient_a: str, ingredient_b: str):
        key = '+'.join(sorted((ingredient_a, ingredient_b)))
        return key, self.recipes.get(key)

    def known_elements(self, values: Iterable[Any]) -> set[str]:
        """Оставить только id, которые есть в каталоге: клиенту не доверяем."""
        return {value for value in _texts(values) if value in self.element_ids}

    def known_recipes(self, values: Iterable[Any]) -> set[str]:
        return {value for value in _texts(values) if value in self.recipe_keys}

    def closed_chapters(self, discovered: Iterable[str]) -> set[str]:
        """Глава закрыта, когда открыты все её goals."""
        opened = set(discovered)
        return {chapter_id for chapter_id, goals in self.chapters if goals and goals <= opened}

    def earned_achievements(
        self, discovered: Iterable[str], crafted: Iterable[str], attempts: int
    ) -> set[str]:
        """Проверить условия достижений по присланным данным, а не по словам клиента."""
        opened, recipes = set(discovered), set(crafted)
        earned: set[str] = set()
        for achievement in self.achievements:
            kind = achievement['type']
            if kind == 'count' and len(opened) >= achievement['value']:
                earned.add(achievement['id'])
            elif kind == 'elements' and achievement['elements'] <= opened:
                earned.add(achievement['id'])
            elif kind == 'tried' and attempts >= achievement['value']:
                earned.add(achievement['id'])
            elif kind == 'recipes' and len(recipes) >= achievement['value']:
                earned.add(achievement['id'])
        return earned


def _texts(values: Any) -> list[str]:
    """Аккуратно привести присланную коллекцию к списку непустых строк."""
    if values is None or isinstance(values, (str, bytes)):
        return []
    try:
        items = list(values)
    except TypeError:
        return []
    return [item for item in items if isinstance(item, str) and item]


def _stored(value: Any) -> set[str]:
    return set(_texts(value))


def _count(value: Any) -> int:
    """Счётчик попыток: мусор и bool считаются нулём."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    return 0


def _catalog_number(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    number = int(value)
    return number if number >= 0 else None


def _load_catalog(path: Path) -> AlchemyCatalog:
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise RuntimeError(f'Каталог «Алхимии» не найден: {path}') from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(f'Каталог «Алхимии» не читается ({path}): {exc}') from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f'Каталог «Алхимии» повреждён: {path}')
    elements = {str(item['id']) for item in _records(raw.get('elements')) if item.get('id')}
    recipe_map = {
        str(item['key']): (str(item['a']), str(item['b']), str(item['result']))
        for item in _records(raw.get('recipes'))
        if item.get('key') and item.get('a') and item.get('b') and item.get('result')
    }
    recipes = set(recipe_map)
    chapters = tuple(
        (str(item['id']), frozenset(str(goal) for goal in _texts(item.get('goals'))))
        for item in _records(raw.get('chapters')) if item.get('id')
    )
    achievements = []
    for item in _records(raw.get('achievements')):
        kind = str(item.get('type') or '')
        identifier = str(item.get('id') or '')
        value = _catalog_number(item.get('value'))
        goals = frozenset(str(element) for element in _texts(item.get('elements')))
        valid = identifier and kind in ACHIEVEMENT_TYPES
        valid = valid and (bool(goals) if kind == 'elements' else value is not None)
        if not valid:
            logger.warning('Достижение «Алхимии» пропущено: %r', item.get('id'))
            continue
        achievements.append({
            'id': identifier, 'type': kind, 'value': value or 0, 'elements': goals,
        })
    if not elements or not chapters:
        raise RuntimeError(f'Каталог «Алхимии» неполон: {path}')
    return AlchemyCatalog(frozenset(elements), frozenset(recipes), recipe_map,
                          chapters, tuple(achievements))


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


@lru_cache(maxsize=1)
def load_catalog() -> AlchemyCatalog:
    """Каталог игры: одно чтение с диска на процесс."""
    return _load_catalog(CATALOG_PATH)


def _resolve_now(now: Optional[datetime]) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _moscow_day(moment: datetime) -> date:
    return moment.astimezone(MOSCOW).date()


def _discovered_rank_expression():
    # Рейтинг строится только по открытиям подтверждённых серверных рецептов.
    return func.coalesce(func.json_array_length(AlchemyProgress.verified_discovered), 0)


class AlchemyService:
    """Прогресс «Алхимии» в PostgreSQL и начисление очков в общий профиль."""

    def __init__(self, database: Database):
        self.database = database

    async def sync(
        self,
        user_id: int,
        *,
        discovered: Iterable[str] = (),
        crafted: Iterable[str] = (),
        attempts: int = 0,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Импортировать офлайн-сводку без подтверждения рейтинговых наград.

        Клиентское сохранение остаётся доступным в коллекции, но только команда
        ``craft`` может изменять verified-поля, рейтинг или общий счёт.
        """
        catalog = load_catalog()
        moment = _resolve_now(now)
        day = _moscow_day(moment)
        incoming_elements = catalog.known_elements(discovered)
        incoming_recipes = catalog.known_recipes(crafted)
        tried = _count(attempts)

        async with self.database.transaction() as session:
            row = await self._locked_progress(session, user_id)
            stored_elements = _stored(row.discovered)
            stored_recipes = _stored(row.crafted)
            stored_chapters = _stored(row.chapters)
            stored_achievements = _stored(row.achievements)

            merged_elements = stored_elements | incoming_elements
            merged_recipes = stored_recipes | incoming_recipes
            # Прогресс монотонный: заработанное не отзывается более бедным sync.
            merged_chapters = stored_chapters | catalog.closed_chapters(merged_elements)
            merged_achievements = stored_achievements | catalog.earned_achievements(
                merged_elements, merged_recipes, max(row.attempts, tried)
            )

            row.attempts = max(row.attempts, tried)
            row.discovered = sorted(merged_elements)
            row.crafted = sorted(merged_recipes)
            row.chapters = sorted(merged_chapters)
            row.achievements = sorted(merged_achievements)
            row.updated_at = moment
            points_today = row.points_today if row.points_day == day else Decimal('0')

            result = {
                'awarded': 0.0,
                'reward_eligible': False,
                'points_today': float(points_today),
                'points_total': float(row.points_total),
                'remaining_today': float(max(DAILY_POINTS_LIMIT - points_today, Decimal('0'))),
                'goal_streak': int(row.goal_streak or 0),
                'discovered': list(row.discovered),
                'verified_discovered': list(row.verified_discovered),
                'verified_crafted': list(row.verified_crafted),
                'chapters': list(row.chapters),
                'achievements': list(row.achievements),
            }
        return result

    async def craft(
        self, user_id: int, *, command_id: str,
        ingredient_a: str, ingredient_b: str,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Validate one recipe server-side and award only newly verified progress."""
        if not isinstance(command_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', command_id):
            raise MiniAppError(422, 'Некорректный идентификатор опыта')
        if not isinstance(ingredient_a, str) or not isinstance(ingredient_b, str):
            raise MiniAppError(422, 'Некорректные ингредиенты опыта')
        catalog = load_catalog()
        key, recipe = catalog.recipe(ingredient_a, ingredient_b)
        if (recipe is None or ingredient_a not in catalog.element_ids
                or ingredient_b not in catalog.element_ids):
            raise MiniAppError(422, 'Такого превращения нет в каталоге')
        moment = _resolve_now(now)
        day = _moscow_day(moment)
        ingredient_a, ingredient_b = sorted((ingredient_a, ingredient_b))
        result_element = recipe[2]

        async with self.database.transaction() as session:
            row = await self._locked_progress(session, user_id)
            inserted = await session.scalar(pg_insert(AlchemyCraftCommand).values(
                id=command_id, account_id=row.account_id,
                ingredient_a=ingredient_a, ingredient_b=ingredient_b,
                result_element=result_element, result={},
            ).on_conflict_do_nothing()
                .returning(AlchemyCraftCommand.id))
            if not inserted:
                existing = await session.scalar(select(AlchemyCraftCommand).where(
                    AlchemyCraftCommand.id == command_id).with_for_update())
                if existing is None:
                    existing = await session.scalar(select(AlchemyCraftCommand).where(
                        AlchemyCraftCommand.account_id == row.account_id,
                        AlchemyCraftCommand.ingredient_a == ingredient_a,
                        AlchemyCraftCommand.ingredient_b == ingredient_b,
                    ).with_for_update())
                    if existing is not None and existing.result:
                        replay = dict(existing.result)
                        replay['awarded'] = 0.0
                        return replay
                if (existing is None or existing.account_id != row.account_id
                        or existing.ingredient_a != ingredient_a
                        or existing.ingredient_b != ingredient_b):
                    raise MiniAppError(409, 'Идентификатор уже использован для другого опыта')
                if not existing.result:
                    raise MiniAppError(409, 'Опыт ещё обрабатывается; повтори позже')
                return existing.result

            verified_elements = _stored(row.verified_discovered) | BASE_ELEMENTS
            verified_recipes = _stored(row.verified_crafted)
            verified = ingredient_a in verified_elements and ingredient_b in verified_elements

            # Keep the player's collection intact even when this particular craft
            # depends on an offline/imported ingredient and therefore is unrated.
            row.discovered = sorted(_stored(row.discovered) | {result_element})
            row.crafted = sorted(_stored(row.crafted) | {key})
            row.updated_at = moment
            awarded = Decimal('0')

            if verified:
                previous_elements = set(verified_elements)
                verified_elements.add(result_element)
                verified_recipes.add(key)
                chapters = _stored(row.verified_chapters)
                new_chapters = catalog.closed_chapters(verified_elements) - chapters
                chapters.update(new_chapters)
                achievements = _stored(row.verified_achievements)
                earned = catalog.earned_achievements(
                    verified_elements, verified_recipes, attempts=0
                ) - achievements
                # A legacy grant may already exist. Only a newly inserted grant can
                # contribute achievement points, preventing a second payout.
                newly_granted = await self._grant(session, user_id, earned)
                requested = (
                    POINTS_PER_ELEMENT * len(verified_elements - previous_elements)
                    + POINTS_PER_CHAPTER * len(new_chapters)
                    + POINTS_PER_ACHIEVEMENT * newly_granted
                )
                if row.points_day != day:
                    row.points_day = day
                    row.points_today = Decimal('0')
                available = max(DAILY_POINTS_LIMIT - row.points_today, Decimal('0'))
                awarded = min(requested, available)
                row.points_today += awarded
                row.points_total += awarded
                if row.points_today >= DAILY_GOAL_POINTS and row.last_goal_day != day:
                    row.goal_streak = (
                        (row.goal_streak or 0) + 1
                        if row.last_goal_day == day - timedelta(days=1) else 1
                    )
                    row.last_goal_day = day
                row.verified_discovered = sorted(verified_elements)
                row.verified_crafted = sorted(verified_recipes)
                row.verified_chapters = sorted(chapters)
                row.verified_achievements = sorted(achievements | earned)
                row.chapters = sorted(_stored(row.chapters) | catalog.closed_chapters(row.discovered))
                row.achievements = sorted(
                    _stored(row.achievements)
                    | catalog.earned_achievements(row.discovered, row.crafted, row.attempts)
                    | earned
                )
                if awarded:
                    await session.execute(
                        update(User).where(User.id == user_id)
                        .values(global_score=User.global_score + awarded)
                    )

            points_today = row.points_today if row.points_day == day else Decimal('0')
            response = {
                'result': result_element,
                'recipe': key,
                'verified': verified,
                'awarded': float(awarded),
                'points_today': float(points_today),
                'points_total': float(row.points_total),
                'remaining_today': float(max(DAILY_POINTS_LIMIT - points_today, Decimal('0'))),
                'discovered': list(row.discovered),
                'verified_discovered': list(row.verified_discovered),
                'verified_crafted': list(row.verified_crafted),
            }
            receipt = await session.get(AlchemyCraftCommand, command_id)
            receipt.result = response
        return response

    async def progress(self, user_id: int, *, now: Optional[datetime] = None) -> dict[str, Any]:
        """Сводка игрока: место, очки за всё время и дневная цель."""
        rank_expression = _discovered_rank_expression()
        today = _moscow_day(_resolve_now(now))
        async with self.database.transaction() as session:
            row = await session.scalar(select(AlchemyProgress).where(AlchemyProgress.user_id == user_id))
            discovered = len(_stored(row.discovered)) if row else 0
            verified_discovered = len(_stored(row.verified_discovered)) if row else len(BASE_ELEMENTS)
            total_players = await session.scalar(
                select(func.count()).select_from(AlchemyProgress).where(AlchemyProgress.user_id.is_not(None))
            ) or 0
            if row is None:
                # Игрок без строки прогресса всё равно участник: место не выше числа игроков.
                total_players += 1
            ahead = await session.scalar(
                select(func.count()).select_from(AlchemyProgress)
                .where(rank_expression > (len(_stored(row.verified_discovered)) if row else len(BASE_ELEMENTS)),
                       AlchemyProgress.user_id.is_not(None))
            ) or 0
            # Счётчик дня обнуляется сам: очки прошлых суток к цели не относятся.
            points_today = float(row.points_today) if row and row.points_day == today else 0.0
            return {
                'discovered': discovered,
                'verified_discovered': verified_discovered,
                'reward_eligible': False,
                'chapters': len(_stored(row.chapters)) if row else 0,
                'achievements': len(_stored(row.achievements)) if row else 0,
                'verified_chapters': len(_stored(row.verified_chapters)) if row else 0,
                'verified_achievements': len(_stored(row.verified_achievements)) if row else 0,
                'points_total': float(row.points_total) if row else 0.0,
                'points_today': points_today,
                'daily_limit': float(DAILY_POINTS_LIMIT),
                'remaining_today': float(max(DAILY_POINTS_LIMIT - Decimal(str(points_today)), Decimal('0'))),
                'daily_goal': {
                    'target': float(DAILY_GOAL_POINTS),
                    'progress': min(points_today, float(DAILY_GOAL_POINTS)),
                    'done': points_today >= float(DAILY_GOAL_POINTS),
                    'streak': int(row.goal_streak or 0) if row else 0,
                },
                'rank': int(ahead) + 1,
                'total_players': int(total_players),
            }

    async def leaderboard(
        self, *, limit: int = 20, offset: int = 0, user_id: Optional[int] = None
    ) -> dict[str, Any]:
        """Рейтинг по числу открытых элементов; чужие данные не раскрываются.

        `user_id` — только для пометки `is_me`; сам идентификатор в ответ не попадает.
        """
        limit = max(0, min(_count(limit), MAX_LEADERBOARD_LIMIT))
        offset = _count(offset)
        if not limit:
            return {'items': []}
        statement = (
            select(AlchemyProgress.user_id, AlchemyProgress.verified_discovered, User.display_name)
            .join(User, User.id == AlchemyProgress.user_id)
            .order_by(_discovered_rank_expression().desc(), AlchemyProgress.user_id)
            .limit(limit)
            .offset(offset)
        )
        async with self.database.transaction() as session:
            rows = (await session.execute(statement)).all()
        return {'items': [
            {
                'rank': position,
                'display_name': display_name or f'User {row_user_id}',
                'discovered': len(_stored(discovered)),
                'verified_discovered': len(_stored(discovered)),
                'is_me': row_user_id == user_id,
            }
            for position, (row_user_id, discovered, display_name) in enumerate(rows, offset + 1)
        ]}

    async def _locked_progress(self, session: AsyncSession, user_id: int) -> AlchemyProgress:
        """Legacy Telegram resolver; progress is owned by one independent account."""
        await OperationalRepository(session).ensure_user({'id': user_id})
        user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user.account_id is None:
            account = Account(display_name=user.display_name, archived=user.archived,
                bot_blocked=user.bot_blocked, moderation_revision=user.moderation_revision,
                moderation_reason=user.moderation_reason)
            session.add(account)
            await session.flush()
            user.account_id = account.id
        return await self._locked_account_progress(session, user.account_id, user_id=user_id)

    async def _locked_account_progress(self, session, account_id, *, user_id=None):
        statement = select(AlchemyProgress).where(
            AlchemyProgress.account_id == account_id).with_for_update()
        await session.execute(pg_insert(AlchemyProgress).values(
            account_id=account_id, user_id=user_id, discovered=[], crafted=[],
            verified_discovered=sorted(BASE_ELEMENTS), verified_crafted=[],
            verified_chapters=[], verified_achievements=[], chapters=[],
            achievements=[], attempts=0, points_total=Decimal('0'),
            points_today=Decimal('0'), points_day=None,
        ).on_conflict_do_nothing(index_elements=[AlchemyProgress.account_id]))
        row = await session.scalar(statement)
        if row.user_id != user_id:
            raise MiniAppError(409, 'Владелец прогресса не совпадает; требуется явная привязка')
        return row

    @staticmethod
    def _guest_projection(row):
        # Imported offline discoveries are saved, never evidence for rated rewards.
        return {'awarded': 0, 'discovered': list(row.discovered) if row else [],
                'crafted': list(row.crafted) if row else [], 'attempts': row.attempts if row else 0,
                'chapters': list(row.chapters) if row else [],
                'achievements': list(row.achievements) if row else [],
                'points_total': 0, 'points_today': 0, 'remaining_today': 0,
                'goal_streak': 0, 'reward_eligible': False}

    async def guest_progress(self, credential, *, now=None):
        moment = _resolve_now(now)
        auth = GuestAccounts(self.database, clock=lambda: moment.timestamp())
        async with self.database.transaction() as session:
            account, _ = await auth._authorized(session, credential, lock=True)
            row = await session.get(AlchemyProgress, account.id)
            if row is not None and row.user_id is not None:
                raise MiniAppError(409, 'Для этого прогресса требуется подтверждённый вход')
            return self._guest_projection(row)

    async def guest_sync(self, credential, *, expected_account_id, discovered=(), crafted=(), attempts=0, now=None):
        moment = _resolve_now(now)
        catalog = load_catalog()
        auth = GuestAccounts(self.database, clock=lambda: moment.timestamp())
        async with self.database.transaction() as session:
            account, _ = await auth._authorized(session, credential, lock=True)
            if str(account.id) != expected_account_id:
                raise MiniAppError(409, 'Гостевой профиль изменился. Открой игру заново.')
            row = await self._locked_account_progress(session, account.id)
            opened = _stored(row.discovered) | catalog.known_elements(discovered)
            recipes = _stored(row.crafted) | catalog.known_recipes(crafted)
            row.attempts = max(row.attempts, _count(attempts))
            row.discovered, row.crafted = sorted(opened), sorted(recipes)
            row.chapters = sorted(_stored(row.chapters) | catalog.closed_chapters(opened))
            row.achievements = sorted(_stored(row.achievements) |
                catalog.earned_achievements(opened, recipes, row.attempts))
            row.updated_at = moment
            return self._guest_projection(row)

    @staticmethod
    async def _grant(session: AsyncSession, user_id: int, achievement_ids: Iterable[str]) -> int:
        """Выдать награды ровно один раз: уникальность (user_id, chat_id, code)."""
        repository = OperationalRepository(session)
        granted = 0
        for achievement_id in sorted(achievement_ids):
            granted += int(await repository.grant_achievement(
                user_id, f'{ACHIEVEMENT_CODE_PREFIX}{achievement_id}', chat_id=0,
                metadata={'source': 'alchemy'},
            ))
        return granted
