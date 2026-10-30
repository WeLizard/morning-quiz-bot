"""The shared pie tower row: atomic totals, one crossing, participants and a fixed goal.

The SQLite checks use the stdlib driver synchronously (as tests/test_farm_wagers.py does), so no
async SQLite driver is needed; the PostgreSQL check runs with TEST_DATABASE_URL and is skipped without it.
"""
import asyncio

import sqlalchemy as sa

from qw_farm.persistence import Unit, tower_table
from tests.test_farm_oleg_pg import environment, pg_url  # noqa: F401  (pytest fixture)


def sqlite_unit():
    metadata = sa.MetaData()
    tower = tower_table(metadata)
    engine = sa.create_engine('sqlite://')
    metadata.create_all(engine)
    return engine, tower


def test_tower_totals_reach_once_and_keep_the_first_goal():
    engine, tower = sqlite_unit()
    with engine.begin() as connection:
        unit = Unit(connection, {'festival_towers': tower}, asynchronous=False, dialect='sqlite')

        async def run():
            first = await unit.tower_add('posidelki-2026', 5, 1, 40, 100.0)
            assert first == dict(key='posidelki-2026', total=5, goal=40, players=1, reached_at=None)
            second = await unit.tower_add('posidelki-2026', 35, 0, 30, 200.0)
            assert second['total'] == 40 and second['goal'] == 40 and second['players'] == 1
            assert second['reached_at'] == 200.0
            third = await unit.tower_add('posidelki-2026', 5, 1, 40, 300.0)
            assert third['total'] == 45 and third['players'] == 2 and third['reached_at'] == 200.0
            assert await unit.tower_peek('posidelki-2026') == third
        asyncio.run(run())
    engine.dispose()


def test_tower_rows_are_created_per_fair():
    engine, tower = sqlite_unit()
    with engine.begin() as connection:
        unit = Unit(connection, {'festival_towers': tower}, asynchronous=False, dialect='sqlite')

        async def run():
            await unit.tower_add('posidelki-2026', 10, 1, 40, 1.0)
            await unit.tower_add('posidelki-2027', 3, 1, 30, 2.0)
            assert (await unit.tower_peek('posidelki-2026'))['total'] == 10
            assert (await unit.tower_peek('posidelki-2027'))['total'] == 3
            assert await unit.tower_peek('new_year-2027') is None
        asyncio.run(run())
    engine.dispose()


def test_postgres_tower_adds_from_two_farms_atomically_and_reaches_once(pg_url):  # noqa: F811
    async def scenario():
        async with environment(pg_url) as env:
            async def add(value, players, now):
                async with env.db.transaction() as session:
                    return await Unit(session, env.schema).tower_add('posidelki-2026', value, players, 40, now)

            await asyncio.gather(*(add(4, 1, 10.0 + i) for i in range(5)))
            async with env.db.transaction() as session:
                row = await Unit(session, env.schema).tower_peek('posidelki-2026')
            assert row['total'] == 20 and row['players'] == 5 and row['goal'] == 40 and row['reached_at'] is None
            results = await asyncio.gather(add(10, 0, 100.0), add(10, 0, 101.0), add(5, 1, 102.0))
            crossed = {r['reached_at'] for r in results if r['reached_at'] is not None}
            async with env.db.transaction() as session:
                row = await Unit(session, env.schema).tower_peek('posidelki-2026')
            assert row['total'] == 45 and row['players'] == 6 and row['goal'] == 40
            assert row['reached_at'] in crossed and len(crossed) == 1
            # A later fair gets its own row; a new goal is kept only for the new key.
            async with env.db.transaction() as session:
                other = await Unit(session, env.schema).tower_add('posidelki-2027', 3, 1, 30, 200.0)
            assert other == dict(key='posidelki-2027', total=3, goal=30, players=1, reached_at=None)
    asyncio.run(scenario())
