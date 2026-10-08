"""Shared PostgreSQL test fixtures and pure Alchemy catalog checks."""
import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select

from storage.alchemy import BASE_ELEMENTS, AlchemyService, load_catalog
from storage.models import (AchievementGrant, AlchemyCraftCommand, AlchemyProgress,
                            User)
from storage.repositories import OperationalRepository
from tests.test_postgres_members import USER, pg_env, scenario

OTHER_USER = USER + 1
THIRD_USER = USER + 2
FOURTH_USER = USER + 3
PLAYERS = (USER, OTHER_USER, THIRD_USER, FOURTH_USER)
CATALOG = load_catalog()
FREE_ELEMENTS = sorted(CATALOG.element_ids - BASE_ELEMENTS)
DAY1 = datetime(2026, 9, 4, 20, 59, tzinfo=timezone.utc)
DAY2 = datetime(2026, 9, 4, 21, 1, tzinfo=timezone.utc)


async def prepare(db, names=None):
    async with db.transaction() as session:
        await session.execute(delete(AlchemyCraftCommand))
        await session.execute(delete(AchievementGrant).where(
            AchievementGrant.user_id.in_(PLAYERS)))
        await session.execute(delete(AlchemyProgress).where(
            AlchemyProgress.user_id.in_(PLAYERS)))
        await session.execute(delete(User).where(User.id.in_(PLAYERS)))
        repository = OperationalRepository(session)
        for user_id in PLAYERS:
            await repository.ensure_user({
                'id': user_id,
                'display_name': (names or {}).get(user_id, f'Player {user_id}'),
            })


async def cleanup(db):
    async with db.transaction() as session:
        await session.execute(delete(AlchemyCraftCommand))
        await session.execute(delete(AchievementGrant).where(
            AchievementGrant.user_id.in_(PLAYERS)))
        await session.execute(delete(AlchemyProgress).where(
            AlchemyProgress.user_id.in_(PLAYERS)))
        await session.execute(delete(User).where(User.id.in_(PLAYERS)))


async def stored(db, user_id):
    async with db.transaction() as session:
        return await session.scalar(select(AlchemyProgress).where(
            AlchemyProgress.user_id == user_id))


async def global_score(db, user_id):
    async with db.transaction() as session:
        return (await session.get(User, user_id)).global_score


async def grant_codes(db, user_id):
    async with db.transaction() as session:
        return sorted((await session.scalars(select(AchievementGrant.code).where(
            AchievementGrant.user_id == user_id))).all())


def test_catalog_is_cached_complete_and_recipes_are_canonical():
    assert load_catalog() is load_catalog()
    data_path = Path(__file__).resolve().parents[1] / 'minigames' / 'alchemia-1.0' / 'data.json'
    data = json.loads(data_path.read_text(encoding='utf-8'))
    assert len(CATALOG.element_ids) == len(data['elements'])
    assert len(CATALOG.recipe_keys) == len(data['recipes'])
    assert len(CATALOG.chapters) == len(data['chapters'])
    assert len(CATALOG.achievements) == len(data['achievements'])
    assert CATALOG.recipe('water', 'fire')[0] == CATALOG.recipe('fire', 'water')[0]
    assert CATALOG.recipe('water', 'fire')[1][2] == 'steam'
    assert len(FREE_ELEMENTS) >= 41


def test_missing_catalog_file_raises_runtime_error(tmp_path):
    from storage.alchemy import _load_catalog
    import pytest

    with pytest.raises(RuntimeError, match='не найден'):
        _load_catalog(tmp_path / 'missing.json')
