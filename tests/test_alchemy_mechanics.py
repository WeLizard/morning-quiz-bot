"""Серверные механики «Алхимии»: только PostgreSQL, синтетические игроки.

Фикстура `pg_env` и сценарий берутся из tests.test_postgres_members; без
TEST_DATABASE_URL весь файл пропускается.
"""

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from storage.alchemy import AlchemyService, load_catalog
from storage.models import AchievementGrant, AlchemyProgress, User
from storage.repositories import OperationalRepository
from tests.test_postgres_members import USER, pg_env, scenario


OTHER_USER = USER + 1
THIRD_USER = USER + 2
FOURTH_USER = USER + 3
PLAYERS = (USER, OTHER_USER, THIRD_USER, FOURTH_USER)

CATALOG = load_catalog()
# Элементы вне целей глав и вне достижений типа «elements»: их открытие не
# закрывает главу и не даёт достижений, поэтому очки считаются ровно по 2.
CHAPTER_GOALS = {goal for _, goals in CATALOG.chapters for goal in goals}
BUNDLE_ELEMENTS = {element for item in CATALOG.achievements
                   if item['type'] == 'elements' for element in item['elements']}
FREE_ELEMENTS = sorted(CATALOG.element_ids - CHAPTER_GOALS - BUNDLE_ELEMENTS)

SPARK_ID, SPARK_GOALS = CATALOG.chapters[0]
SPARK_ELEMENTS = sorted(SPARK_GOALS)
DAY1 = datetime(2026, 9, 4, 20, 59, tzinfo=timezone.utc)   # Москва: 23:59 того же дня
DAY2 = datetime(2026, 9, 4, 21, 1, tzinfo=timezone.utc)    # Москва: 00:01 следующих суток


async def prepare(db, names=None):
    """Чистое состояние для игроков файла: прошлый прогресс убирается."""
    async with db.transaction() as session:
        await session.execute(delete(AchievementGrant).where(AchievementGrant.user_id.in_(PLAYERS)))
        await session.execute(delete(AlchemyProgress).where(AlchemyProgress.user_id.in_(PLAYERS)))
        await session.execute(delete(User).where(User.id.in_(PLAYERS)))
        repository = OperationalRepository(session)
        for user_id in PLAYERS:
            await repository.ensure_user({
                'id': user_id, 'display_name': (names or {}).get(user_id, f'Player {user_id}'),
            })


async def cleanup(db):
    async with db.transaction() as session:
        await session.execute(delete(AchievementGrant).where(AchievementGrant.user_id.in_(PLAYERS)))
        await session.execute(delete(AlchemyProgress).where(AlchemyProgress.user_id.in_(PLAYERS)))
        await session.execute(delete(User).where(User.id.in_(PLAYERS)))


async def stored(db, user_id):
    async with db.transaction() as session:
        return await session.get(AlchemyProgress, user_id)


async def global_score(db, user_id):
    async with db.transaction() as session:
        return (await session.get(User, user_id)).global_score


async def grant_codes(db, user_id):
    async with db.transaction() as session:
        return sorted((await session.scalars(select(AchievementGrant.code).where(
            AchievementGrant.user_id == user_id))).all())


def test_first_sync_awards_two_three_five_and_grants_once(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            try:
                await prepare(db)
                service = AlchemyService(db)
                # Глава «spark»: 5 элементов × 2 + глава 3 + достижение «first» 5.
                result = await service.sync(USER, discovered=SPARK_ELEMENTS, now=DAY1)
                assert result['awarded'] == 18.0
                assert result['points_today'] == result['points_total'] == 18.0
                assert result['remaining_today'] == 12.0
                assert result['discovered'] == SPARK_ELEMENTS
                assert result['chapters'] == [SPARK_ID]
                assert result['achievements'] == ['first']
                assert await global_score(db, USER) == Decimal('18.000')

                # Повторный sync с теми же данными: 0 очков и ни одного дубля.
                repeat = await service.sync(
                    USER, discovered=list(reversed(SPARK_ELEMENTS)), now=DAY1)
                assert repeat['awarded'] == 0.0
                assert repeat['points_today'] == 18.0
                assert repeat['points_total'] == 18.0
                assert repeat['discovered'] == SPARK_ELEMENTS
                assert await grant_codes(db, USER) == ['alchemy_first']
                assert await global_score(db, USER) == Decimal('18.000')

                row = await stored(db, USER)
                assert row.points_total == Decimal('18.000')
                assert row.points_today == Decimal('18.000')
                assert row.points_day == date(2026, 9, 4)
                assert row.updated_at is not None
            finally:
                await cleanup(db)
    asyncio.run(run())


def test_grant_row_is_written_exactly_once(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            try:
                await prepare(db)
                service = AlchemyService(db)
                for _ in range(3):
                    await service.sync(USER, discovered=SPARK_ELEMENTS)
                async with db.transaction() as session:
                    grants = (await session.scalars(select(AchievementGrant).where(
                        AchievementGrant.user_id == USER))).all()
                assert len(grants) == 1
                assert grants[0].code == 'alchemy_first'
                assert grants[0].chat_id == 0
                assert grants[0].metadata_json == {'source': 'alchemy'}
            finally:
                await cleanup(db)
    asyncio.run(run())


def test_daily_cap_keeps_thirty_points_and_never_carries_the_rest(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            try:
                assert len(FREE_ELEMENTS) >= 41
                await prepare(db)
                service = AlchemyService(db)
                first = FREE_ELEMENTS[:20]
                # 20 элементов = 40 очков, но суточный потолок оставляет 30.
                capped = await service.sync(USER, discovered=first, now=DAY1)
                assert capped['awarded'] == 30.0
                assert capped['points_today'] == 30.0
                assert capped['remaining_today'] == 0.0
                assert await global_score(db, USER) == Decimal('30.000')

                # Тот же день: новые элементы есть, а очки уже не начисляются.
                more = await service.sync(USER, discovered=first + FREE_ELEMENTS[20:40], now=DAY1)
                assert more['awarded'] == 0.0
                assert more['points_total'] == 30.0
                assert len(more['discovered']) == 40
                assert await global_score(db, USER) == Decimal('30.000')

                # Новые сутки: счётчик обнулился, но старый перебор не вернулся.
                next_day = await service.sync(USER, discovered=first, now=DAY2)
                assert next_day['awarded'] == 0.0
                assert next_day['points_today'] == 0.0
                assert next_day['remaining_today'] == 30.0
                added = await service.sync(USER, discovered=[FREE_ELEMENTS[40]], now=DAY2)
                assert added['awarded'] == 2.0
                assert added['points_today'] == 2.0
                assert added['points_total'] == 32.0
            finally:
                await cleanup(db)
    asyncio.run(run())


def test_daily_counter_uses_moscow_midnight(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            try:
                await prepare(db)
                service = AlchemyService(db)
                first = await service.sync(USER, discovered=FREE_ELEMENTS[:20], now=DAY1)
                assert first['awarded'] == 30.0
                # 21:01 UTC — это уже следующие сутки по Москве.
                second = await service.sync(
                    USER, discovered=[FREE_ELEMENTS[20]], now=DAY2,
                )
                assert second['awarded'] == 2.0
                assert second['points_today'] == 2.0
                assert (await stored(db, USER)).points_day == date(2026, 9, 5)
            finally:
                await cleanup(db)
    asyncio.run(run())


def test_unknown_ids_and_junk_are_ignored(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            try:
                await prepare(db)
                service = AlchemyService(db)
                recipe_key = sorted(CATALOG.recipe_keys)[0]
                result = await service.sync(
                    USER,
                    discovered=['water', 'nope', '', None, 42, 'water'],
                    crafted=[recipe_key, 'fake+recipe', 7],
                    attempts='много',
                )
                assert result['discovered'] == ['water']
                assert result['awarded'] == 2.0
                row = await stored(db, USER)
                assert row.discovered == ['water']
                assert row.crafted == [recipe_key]
                assert await grant_codes(db, USER) == []
            finally:
                await cleanup(db)
    asyncio.run(run())


def test_achievement_needs_its_own_condition(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            try:
                await prepare(db)
                service = AlchemyService(db)
                # «tried»: при 49 попытках порог 50 ещё не взят.
                near = await service.sync(USER, attempts=49)
                assert near['awarded'] == 0.0
                assert near['achievements'] == []
                earned = await service.sync(USER, attempts=50)
                assert earned['awarded'] == 5.0
                assert earned['achievements'] == ['persistent']
                # Более бедный sync не отзывает заработанное.
                again = await service.sync(USER, attempts=0)
                assert again['awarded'] == 0.0
                assert again['achievements'] == ['persistent']

                # «elements»: нужны оба элемента из условия.
                half = await service.sync(USER, discovered=['cat'])
                assert half['awarded'] == 2.0
                assert 'pets' not in half['achievements']
                full = await service.sync(USER, discovered=['cat', 'mouse'])
                assert 'pets' in full['achievements']
                assert full['awarded'] == 7.0  # новый mouse 2 + достижение 5
            finally:
                await cleanup(db)
    asyncio.run(run())


def test_recipes_achievement_counts_only_working_combinations(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            try:
                await prepare(db)
                service = AlchemyService(db)
                keys = sorted(CATALOG.recipe_keys)
                short = await service.sync(USER, crafted=keys[:99] + ['fake+recipe'])
                assert short['achievements'] == []
                assert short['awarded'] == 0.0
                full = await service.sync(USER, crafted=keys[:100])
                assert full['achievements'] == ['recipes']
                assert full['awarded'] == 5.0
            finally:
                await cleanup(db)
    asyncio.run(run())


def test_chapter_closes_only_when_every_goal_is_open(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            try:
                await prepare(db)
                service = AlchemyService(db)
                almost = await service.sync(USER, discovered=SPARK_ELEMENTS[:4])
                assert almost['chapters'] == []
                assert almost['awarded'] == 8.0
                closed = await service.sync(USER, discovered=SPARK_ELEMENTS)
                assert closed['chapters'] == [SPARK_ID]
                assert closed['awarded'] == 10.0  # 5-й элемент 2 + глава 3 + достижение 5
                assert closed['points_total'] == 18.0
            finally:
                await cleanup(db)
    asyncio.run(run())


def test_leaderboard_sorts_and_hides_foreign_players(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            try:
                await prepare(db, {USER: 'Первый', OTHER_USER: 'Второй',
                                   THIRD_USER: 'Третий', FOURTH_USER: 'Четвёртый'})
                service = AlchemyService(db)
                await service.sync(USER, discovered=SPARK_ELEMENTS)
                await service.sync(OTHER_USER, discovered=SPARK_ELEMENTS)
                await service.sync(THIRD_USER, discovered=FREE_ELEMENTS[:2])
                await service.sync(FOURTH_USER)

                board = await service.leaderboard(limit=10, user_id=THIRD_USER)
                items = board['items']
                assert [item['discovered'] for item in items] == [5, 5, 2, 0]
                # Равные результаты: первым идёт меньший user_id.
                assert [item['display_name'] for item in items] == [
                    'Первый', 'Второй', 'Третий', 'Четвёртый']
                assert [item['rank'] for item in items] == [1, 2, 3, 4]
                assert [item['is_me'] for item in items] == [False, False, True, False]
                for item in items:
                    assert set(item) == {'rank', 'display_name', 'discovered', 'is_me'}

                page = await service.leaderboard(limit=2, offset=1)
                assert [item['rank'] for item in page['items']] == [2, 3]
                assert all(item['is_me'] is False for item in page['items'])
            finally:
                await cleanup(db)
    asyncio.run(run())


def test_progress_reports_place_and_empty_player(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            try:
                await prepare(db)
                service = AlchemyService(db)
                await service.sync(USER, discovered=SPARK_ELEMENTS)
                await service.sync(OTHER_USER, discovered=FREE_ELEMENTS[:2])

                best = await service.progress(USER)
                assert (best['discovered'], best['chapters'], best['achievements']) == (5, 1, 1)
                assert best['points_total'] == 18.0
                assert best['rank'] == 1
                assert best['total_players'] == 2

                last = await service.progress(THIRD_USER)  # строки ещё нет
                assert last['discovered'] == 0 and last['points_total'] == 0.0
                assert last['rank'] == 3  # двое впереди, сам игрок тоже считается
                assert last['total_players'] == 3
            finally:
                await cleanup(db)
    asyncio.run(run())


def test_parallel_sync_of_one_player_awards_once(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            try:
                await prepare(db)
                services = [AlchemyService(db) for _ in range(3)]
                results = await asyncio.gather(*[
                    service.sync(USER, discovered=SPARK_ELEMENTS) for service in services
                ])
                assert sum(result['awarded'] for result in results) == 18.0
                assert await global_score(db, USER) == Decimal('18.000')
                assert await grant_codes(db, USER) == ['alchemy_first']
                row = await stored(db, USER)
                assert row.points_total == Decimal('18.000')
            finally:
                await cleanup(db)
    asyncio.run(run())


def test_sync_creates_missing_profile_and_progress(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            try:
                await cleanup(db)  # игроков нет вообще: sync обязан их создать
                service = AlchemyService(db)
                result = await service.sync(FOURTH_USER, discovered=['water'])
                assert result['awarded'] == 2.0
                async with db.transaction() as session:
                    assert await session.get(User, FOURTH_USER) is not None
                    assert await session.get(AlchemyProgress, FOURTH_USER) is not None
            finally:
                await cleanup(db)
    asyncio.run(run())


def test_catalog_is_cached_and_complete():
    assert load_catalog() is load_catalog()
    # Состав сверяем с самим data.json: контент растёт от версии к версии,
    # и жёсткие числа здесь ломали бы тест на каждом расширении.
    data = json.loads((Path(__file__).resolve().parents[1] / 'minigames' / 'alchemia-1.0' / 'data.json').read_text(encoding='utf-8'))
    assert len(CATALOG.element_ids) == len(data['elements'])
    assert len(CATALOG.recipe_keys) == len(data['recipes'])
    assert len(CATALOG.chapters) == len(data['chapters'])
    assert len(CATALOG.achievements) == len(data['achievements'])
    assert len(FREE_ELEMENTS) >= 41


def test_catalog_missing_file_raises_runtime_error(tmp_path):
    from storage import alchemy as module
    with pytest.raises(RuntimeError, match='не найден'):
        module._load_catalog(tmp_path / 'data.json')


def test_progress_shows_daily_goal_and_remaining_limit(pg_env):
    """Игрок должен видеть цель дня и сколько ещё очков можно набрать сегодня."""
    async def run():
        async with scenario(pg_env) as db:
            try:
                await prepare(db)
                service = AlchemyService(db)
                # Очки за достижения зависят от каталога, поэтому ожидания считаем
                # от фактического начисления, а не от числа открытых элементов.
                start = await service.sync(USER, discovered=FREE_ELEMENTS[:3])
                earned = start['points_today']
                report = await service.progress(USER)
                assert report['points_today'] == earned
                assert report['remaining_today'] == 30.0 - earned
                assert report['daily_limit'] == 30.0
                assert report['daily_goal']['target'] == 10.0
                assert report['daily_goal']['progress'] == min(earned, 10.0)
                assert report['daily_goal']['done'] is (earned >= 10.0)

                await service.sync(USER, discovered=FREE_ELEMENTS)   # догоняем до потолка
                capped = await service.progress(USER)
                assert capped['points_today'] == 30.0 and capped['remaining_today'] == 0.0
                assert capped['daily_goal'] == {'target': 10.0, 'progress': 10.0, 'done': True, 'streak': 1}
            finally:
                await cleanup(db)
    asyncio.run(run())


def test_progress_forgets_points_of_a_previous_moscow_day(pg_env):
    """Очки прошлых суток в цель дня не идут, а накопленное остаётся."""
    async def run():
        async with scenario(pg_env) as db:
            try:
                await prepare(db)
                service = AlchemyService(db)
                synced = await service.sync(USER, discovered=FREE_ELEMENTS[:8], now=DAY1)
                earned = synced['points_today']
                assert earned > 0

                same_day = await service.progress(USER, now=DAY1)
                assert same_day['points_today'] == earned
                assert same_day['remaining_today'] == 30.0 - earned

                next_day = await service.progress(USER, now=DAY2)
                assert next_day['points_today'] == 0.0 and next_day['remaining_today'] == 30.0
                assert next_day['daily_goal'] == {'target': 10.0, 'progress': 0.0, 'done': False, 'streak': 1}
                assert next_day['points_total'] == earned
            finally:
                await cleanup(db)
    asyncio.run(run())


def test_goal_streak_counts_consecutive_moscow_days(pg_env):
    """Серия растёт за закрытую цель дня, повтор в тот же день её не накручивает,
    а пропущенный день начинает серию заново."""
    async def run():
        async with scenario(pg_env) as db:
            try:
                await prepare(db)
                service = AlchemyService(db)

                first = await service.sync(USER, discovered=FREE_ELEMENTS[:8], now=DAY1)
                assert first['points_today'] >= 10.0, 'подготовка теста: цель дня должна закрыться'
                assert first['goal_streak'] == 1

                again = await service.sync(USER, discovered=FREE_ELEMENTS[:9], now=DAY1)
                assert again['goal_streak'] == 1, 'повтор в тот же день серию не накручивает'

                second = await service.sync(USER, discovered=FREE_ELEMENTS[:20], now=DAY2)
                assert second['points_today'] >= 10.0
                assert second['goal_streak'] == 2, 'второй день подряд продолжает серию'

                # Один день пропущен: следующий закрытый день начинает серию заново.
                after_gap = await service.sync(USER, discovered=FREE_ELEMENTS[:40], now=DAY2 + timedelta(days=2))
                assert after_gap['points_today'] >= 10.0
                assert after_gap['goal_streak'] == 1

                report = await service.progress(USER, now=DAY2 + timedelta(days=2))
                assert report['daily_goal']['streak'] == 1
            finally:
                await cleanup(db)
    asyncio.run(run())