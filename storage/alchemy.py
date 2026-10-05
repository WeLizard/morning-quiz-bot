"""Серверные механики «Алхимии»: прогресс, очки и внутриигровые достижения.

Клиент присылает только собственное локальное состояние, поэтому открытые
элементы, закрытые главы и достижения пересчитываются здесь по каталогу
`minigames/alchemia-1.0/data.json`. Файл большой (276 КБ), поэтому читается
один раз на процесс.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .database import Database
from .models import AlchemyProgress, User
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


@dataclass(frozen=True)
class AlchemyCatalog:
    """Неизменяемый срез контента игры, прочитанный из data.json."""

    element_ids: frozenset[str]
    recipe_keys: frozenset[str]
    chapters: tuple[tuple[str, frozenset[str]], ...]
    achievements: tuple[dict[str, Any], ...]

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
    recipes = {str(item['key']) for item in _records(raw.get('recipes')) if item.get('key')}
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
    return AlchemyCatalog(frozenset(elements), frozenset(recipes), chapters, tuple(achievements))


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
    # json_array_length даёт NULL для не-массива, поэтому coalesce обязателен.
    return func.coalesce(func.json_array_length(AlchemyProgress.discovered), 0)


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
        """Принять состояние игры, досчитать новое и начислить очки.

        Очки идут только за первое открытие: элемент — 2, закрытая глава — 3,
        достижение — 5. Суточный потолок (30, сутки по Москве) лишнее отсекает
        без переноса на следующий день.
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
                merged_elements, merged_recipes, tried
            )

            new_chapters = merged_chapters - stored_chapters
            new_achievements = merged_achievements - stored_achievements
            requested = (
                POINTS_PER_ELEMENT * len(merged_elements - stored_elements)
                + POINTS_PER_CHAPTER * len(new_chapters)
                + POINTS_PER_ACHIEVEMENT * len(new_achievements)
            )
            if row.points_day != day:
                row.points_day = day
                row.points_today = Decimal('0')
            available = max(DAILY_POINTS_LIMIT - row.points_today, Decimal('0'))
            awarded = min(requested, available)
            if awarded < requested:
                logger.debug(
                    'Алхимия: суточный потолок срезал %s очков у %s', requested - awarded, user_id
                )

            row.discovered = sorted(merged_elements)
            row.crafted = sorted(merged_recipes)
            row.chapters = sorted(merged_chapters)
            row.achievements = sorted(merged_achievements)
            row.points_today += awarded
            row.points_total += awarded
            row.updated_at = moment
            if awarded:
                await session.execute(
                    update(User).where(User.id == user_id)
                    .values(global_score=User.global_score + awarded)
                )
            await self._grant(session, user_id, new_achievements)

            result = {
                'awarded': float(awarded),
                'points_today': float(row.points_today),
                'points_total': float(row.points_total),
                'remaining_today': float(max(DAILY_POINTS_LIMIT - row.points_today, Decimal('0'))),
                'discovered': list(row.discovered),
                'chapters': list(row.chapters),
                'achievements': list(row.achievements),
            }
        return result

    async def progress(self, user_id: int, *, now: Optional[datetime] = None) -> dict[str, Any]:
        """Сводка игрока: место, очки за всё время и дневная цель."""
        rank_expression = _discovered_rank_expression()
        today = _moscow_day(_resolve_now(now))
        async with self.database.transaction() as session:
            row = await session.get(AlchemyProgress, user_id)
            discovered = len(_stored(row.discovered)) if row else 0
            total_players = await session.scalar(
                select(func.count()).select_from(AlchemyProgress)
            ) or 0
            if row is None:
                # Игрок без строки прогресса всё равно участник: место не выше числа игроков.
                total_players += 1
            ahead = await session.scalar(
                select(func.count()).select_from(AlchemyProgress)
                .where(rank_expression > discovered)
            ) or 0
            # Счётчик дня обнуляется сам: очки прошлых суток к цели не относятся.
            points_today = float(row.points_today) if row and row.points_day == today else 0.0
            return {
                'discovered': discovered,
                'chapters': len(_stored(row.chapters)) if row else 0,
                'achievements': len(_stored(row.achievements)) if row else 0,
                'points_total': float(row.points_total) if row else 0.0,
                'points_today': points_today,
                'daily_limit': float(DAILY_POINTS_LIMIT),
                'remaining_today': float(max(DAILY_POINTS_LIMIT - Decimal(str(points_today)), Decimal('0'))),
                'daily_goal': {
                    'target': float(DAILY_GOAL_POINTS),
                    'progress': min(points_today, float(DAILY_GOAL_POINTS)),
                    'done': points_today >= float(DAILY_GOAL_POINTS),
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
            select(AlchemyProgress.user_id, AlchemyProgress.discovered, User.display_name)
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
                'is_me': row_user_id == user_id,
            }
            for position, (row_user_id, discovered, display_name) in enumerate(rows, offset + 1)
        ]}

    async def _locked_progress(self, session: AsyncSession, user_id: int) -> AlchemyProgress:
        """Строка прогресса под блокировкой; отсутствующую создаём гонко-безопасно."""
        await OperationalRepository(session).ensure_user({'id': user_id})
        statement = select(AlchemyProgress).where(
            AlchemyProgress.user_id == user_id
        ).with_for_update()
        row = await session.scalar(statement)
        if row is None:
            await session.execute(
                pg_insert(AlchemyProgress)
                .values(
                    user_id=user_id, discovered=[], crafted=[], chapters=[], achievements=[],
                    points_total=Decimal('0'), points_today=Decimal('0'), points_day=None,
                )
                .on_conflict_do_nothing(index_elements=[AlchemyProgress.user_id])
            )
            row = await session.scalar(statement)
        return row

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
