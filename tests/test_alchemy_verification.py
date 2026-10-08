"""Server-authoritative Alchemy rewards; runs only on disposable PostgreSQL."""
import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from storage.alchemy import BASE_ELEMENTS, AlchemyService, load_catalog
from storage.models import AlchemyCraftCommand, AlchemyProgress, User
from storage.mini_app import MiniAppError
from storage.repositories import OperationalRepository
from tests.local_database import isolated_database
from tests.test_alchemy_mechanics import (DAY1, DAY2, USER, OTHER_USER, grant_codes,
                                         global_score, prepare, stored)
from tests.test_postgres_members import pg_env

CATALOG = load_catalog()
SPARK_GOALS = next(goals for chapter, goals in CATALOG.chapters if chapter == 'spark')


CATALOG = load_catalog()
BASE_RECIPE = next(
    (key, recipe) for key, recipe in CATALOG.recipes.items()
    if recipe[0] in BASE_ELEMENTS and recipe[1] in BASE_ELEMENTS
)
UNTRUSTED_RECIPE = next(
    (key, recipe) for key, recipe in CATALOG.recipes.items()
    if recipe[0] not in BASE_ELEMENTS and recipe[1] not in BASE_ELEMENTS
)


def test_untrusted_full_catalog_import_preserves_collection_without_rewards(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            await prepare(db)
            result = await AlchemyService(db).sync(
                USER, discovered=sorted(CATALOG.element_ids) + ['unknown', '', None, 42],
                crafted=sorted(CATALOG.recipe_keys) + ['not+a+recipe'], attempts=100_000,
            )
            assert set(result['discovered']) == CATALOG.element_ids
            assert result['awarded'] == 0
            assert result['reward_eligible'] is False
            assert set(result['verified_discovered']) == BASE_ELEMENTS
            assert result['verified_crafted'] == []
            assert await global_score(db, USER) == Decimal('0.000')
            async with db.transaction() as session:
                row = await session.scalar(select(AlchemyProgress).where(
                    AlchemyProgress.user_id == USER))
                assert row.points_total == Decimal('0')
                assert row.achievements  # legacy/local achievement view is retained
                assert await grant_codes(db, USER) == []
                assert (await session.scalars(select(AlchemyCraftCommand))).all() == []
    asyncio.run(run())


def test_verified_server_recipe_awards_once_and_replays_idempotently(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            await prepare(db)
            service = AlchemyService(db)
            key, (ingredient_a, ingredient_b, result_element) = BASE_RECIPE
            result = await service.craft(
                USER, command_id='verified-command-0001',
                ingredient_a=ingredient_a, ingredient_b=ingredient_b, now=DAY1,
            )
            assert result['verified'] is True
            assert result['recipe'] == key and result['result'] == result_element
            assert result['awarded'] >= 2
            assert result_element in result['verified_discovered']
            assert await global_score(db, USER) == Decimal(str(result['awarded']))

            replay = await service.craft(
                USER, command_id='verified-command-0001',
                ingredient_a=ingredient_b, ingredient_b=ingredient_a, now=DAY1,
            )
            assert replay == result
            second_command = await service.craft(
                USER, command_id='verified-command-0002',
                ingredient_a=ingredient_a, ingredient_b=ingredient_b, now=DAY1,
            )
            assert second_command['awarded'] == 0
            assert await global_score(db, USER) == Decimal(str(result['awarded']))
            async with db.transaction() as session:
                commands = (await session.scalars(select(AlchemyCraftCommand))).all()
                assert len(commands) == 1
    asyncio.run(run())


def test_legacy_score_and_collection_are_not_clawed_back(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            await prepare(db)
            service = AlchemyService(db)
            await service.sync(USER, discovered=['water', 'earth', 'steam'])
            async with db.transaction() as session:
                row = await session.scalar(select(AlchemyProgress).where(
                    AlchemyProgress.user_id == USER))
                user = await session.get(User, USER)
                row.points_total = Decimal('123.000')
                row.points_today = Decimal('7.000')
                user.global_score = Decimal('456.000')
                await OperationalRepository(session).grant_achievement(
                    USER, 'alchemy_legacy', chat_id=0, metadata={'source': 'alchemy'})

            imported = await service.sync(USER, discovered=sorted(CATALOG.element_ids),
                                          crafted=sorted(CATALOG.recipe_keys), attempts=100_000)
            assert imported['awarded'] == 0
            assert set(imported['discovered']) == CATALOG.element_ids
            assert imported['points_total'] == 123
            assert await global_score(db, USER) == Decimal('456.000')
            assert await grant_codes(db, USER) == ['alchemy_legacy']
    asyncio.run(run())


def test_invalid_recipe_is_rejected(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            await prepare(db)
            with pytest.raises(MiniAppError) as error:
                await AlchemyService(db).craft(
                    USER, command_id='invalid-recipe-command',
                    ingredient_a='water', ingredient_b='not-an-element')
            assert error.value.status == 422
    asyncio.run(run())


def test_unverified_imported_ingredients_cannot_be_promoted_to_ranked_progress(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            await prepare(db)
            service = AlchemyService(db)
            await service.sync(USER, discovered=sorted(CATALOG.element_ids))
            key, (ingredient_a, ingredient_b, result_element) = UNTRUSTED_RECIPE
            result = await service.craft(
                USER, command_id='unverified-command-0001',
                ingredient_a=ingredient_a, ingredient_b=ingredient_b,
            )
            assert result['verified'] is False
            assert result['awarded'] == 0
            assert result_element in result['discovered']
            assert result_element not in result['verified_discovered']
            assert await global_score(db, USER) == Decimal('0.000')
            assert result['recipe'] == key
    asyncio.run(run())


def test_server_accepts_catalog_self_combinations(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            await prepare(db)
            result = await AlchemyService(db).craft(
                USER, command_id='self-combination-command',
                ingredient_a='earth', ingredient_b='earth')
            assert result['verified'] is True
            assert result['result'] == 'stone'
            assert 'stone' in result['verified_discovered']
    asyncio.run(run())


def test_verified_progress_survives_later_untrusted_sync(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            await prepare(db)
            service = AlchemyService(db)
            _, (ingredient_a, ingredient_b, result_element) = BASE_RECIPE
            craft = await service.craft(
                USER, command_id='verified-then-import-command',
                ingredient_a=ingredient_a, ingredient_b=ingredient_b)
            imported = await service.sync(USER, discovered=sorted(CATALOG.element_ids),
                                          crafted=sorted(CATALOG.recipe_keys))
            assert imported['awarded'] == 0
            assert result_element in imported['verified_discovered']
            assert set(imported['verified_crafted']) == {craft['recipe']}
            assert await global_score(db, USER) == Decimal(str(craft['awarded']))
    asyncio.run(run())


def test_verified_achievements_and_chapter_are_awarded_from_server_events(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            await prepare(db)
            service = AlchemyService(db)
            results = []
            for index, goal in enumerate(sorted(SPARK_GOALS)):
                ingredients = next(recipe for recipe in CATALOG.recipes.values()
                                   if recipe[2] == goal)
                assert ingredients[0] in BASE_ELEMENTS and ingredients[1] in BASE_ELEMENTS
                results.append(await service.craft(
                    USER, command_id=f'spark-chapter-command-{index:02d}',
                    ingredient_a=ingredients[0], ingredient_b=ingredients[1]))
            row = await stored(db, USER)
            assert set(SPARK_GOALS).issubset(set(row.verified_discovered))
            assert 'spark' in row.verified_chapters
            assert 'first' in row.verified_achievements
            assert 'alchemy_first' in await grant_codes(db, USER)
            assert sum(result['awarded'] for result in results) > 10
    asyncio.run(run())


def test_verified_rewards_keep_daily_cap_and_reset_at_moscow_midnight(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            await prepare(db)
            service = AlchemyService(db)
            await service.sync(USER)  # create the account-owned progress row
            async with db.transaction() as session:
                row = await session.scalar(select(AlchemyProgress).where(
                    AlchemyProgress.user_id == USER))
                user = await session.get(User, USER)
                row.points_day = date(2026, 9, 4)
                row.points_today = Decimal('29')
                row.points_total = Decimal('29')
                user.global_score = Decimal('29')
            recipes = [recipe for recipe in CATALOG.recipes.values()
                       if recipe[0] in BASE_ELEMENTS and recipe[1] in BASE_ELEMENTS]
            first = await service.craft(
                USER, command_id='cap-command-first', ingredient_a=recipes[0][0],
                ingredient_b=recipes[0][1], now=DAY1)
            assert first['awarded'] == 1
            assert first['points_today'] == 30
            same_day = await service.craft(
                USER, command_id='cap-command-second', ingredient_a=recipes[1][0],
                ingredient_b=recipes[1][1], now=DAY1)
            assert same_day['awarded'] == 0 and same_day['points_total'] == 30
            next_day = await service.craft(
                USER, command_id='cap-command-next-day', ingredient_a=recipes[2][0],
                ingredient_b=recipes[2][1], now=DAY2)
            assert next_day['awarded'] > 0
            assert next_day['points_today'] == next_day['awarded']
            assert next_day['points_total'] > 30
    asyncio.run(run())


def test_craft_command_id_cannot_be_reused_for_another_actor_or_recipe(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            await prepare(db)
            service = AlchemyService(db)
            _, (ingredient_a, ingredient_b, _) = BASE_RECIPE
            await service.craft(USER, command_id='cross-account-command-01',
                                ingredient_a=ingredient_a, ingredient_b=ingredient_b)
            alternate = next((recipe for recipe in CATALOG.recipes.values()
                              if recipe[0] in BASE_ELEMENTS and recipe[1] in BASE_ELEMENTS
                              and {recipe[0], recipe[1]} != {ingredient_a, ingredient_b}))
            with pytest.raises(MiniAppError) as same_actor_error:
                await service.craft(USER, command_id='cross-account-command-01',
                                    ingredient_a=alternate[0], ingredient_b=alternate[1])
            assert same_actor_error.value.status == 409
            with pytest.raises(MiniAppError) as error:
                await service.craft(OTHER_USER, command_id='cross-account-command-01',
                                    ingredient_a=ingredient_a, ingredient_b=ingredient_b)
            assert getattr(error.value, 'status', None) == 409
    asyncio.run(run())


def test_leaderboard_ignores_unverified_imports(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            await prepare(db, {USER: 'Импорт', OTHER_USER: 'Подтверждение'})
            service = AlchemyService(db)
            await service.sync(USER, discovered=sorted(CATALOG.element_ids))
            _, (ingredient_a, ingredient_b, _) = BASE_RECIPE
            await service.craft(OTHER_USER, command_id='ranked-recipe-command',
                                ingredient_a=ingredient_a, ingredient_b=ingredient_b)
            board = await service.leaderboard(limit=10)
            assert board['items'][0]['display_name'] == 'Подтверждение'
            assert board['items'][0]['verified_discovered'] == len(BASE_ELEMENTS) + 1
            assert board['items'][1]['display_name'] == 'Импорт'
            assert board['items'][1]['verified_discovered'] == len(BASE_ELEMENTS)
    asyncio.run(run())


def test_parallel_duplicate_recipe_commands_award_once(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            await prepare(db)
            _, (ingredient_a, ingredient_b, _) = BASE_RECIPE
            service = AlchemyService(db)
            results = await asyncio.gather(*[
                service.craft(USER, command_id=f'parallel-command-{index:02d}',
                              ingredient_a=ingredient_a, ingredient_b=ingredient_b)
                for index in range(10)
            ])
            assert sum(result['awarded'] for result in results) == results[0]['awarded']
            assert sum(result['awarded'] > 0 for result in results) == 1
            async with db.transaction() as session:
                assert len((await session.scalars(select(AlchemyCraftCommand))).all()) == 1
                assert (await session.get(User, USER)).global_score == Decimal(
                    str(results[0]['awarded']))
    asyncio.run(run())
