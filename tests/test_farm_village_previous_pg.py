"""The village fund keeps the season that has just ended visible: result, own share and the farm that gave the most."""

import asyncio
import os
from uuid import uuid4

import pytest

from qw_farm import economy
from qw_farm.catalog import FUND_LEVEL, LEVELS
from qw_farm.domain import new_farm
from qw_farm.expansion import upgrade_state
from qw_farm.persistence import Unit
from qw_farm.service import FarmService, Principal
from storage.database import normalize_database_url
from storage.models import Account
from tests.test_farm_oleg_pg import environment

DAY = 86400


@pytest.fixture
def pg_url():
    raw = os.getenv('TEST_DATABASE_URL')
    if not raw:
        pytest.skip('TEST_DATABASE_URL is not configured')
    return normalize_database_url(raw)


async def farm_with(env, name, season, personal, now):
    account = uuid4()
    async with env.db.transaction() as session:
        session.add(Account(id=account, display_name=name))
        await session.flush()
        farm = upgrade_state(new_farm(str(uuid4()), name, now))
        farm['xp'] = LEVELS[FUND_LEVEL]
        if personal:
            rec = economy.record(farm, season, FUND_LEVEL)
            rec['joined'] = True
            rec['personal'] = personal
        await Unit(session, env.schema).save(farm, account)
    return account, farm['id'], farm['name']


def test_previous_season_summary_names_the_top_farm_and_own_share(pg_url):
    async def scenario():
        async with environment(pg_url) as env:
            now = 1_800_000_000
            season = economy.season_of(now)
            previous = season - 1
            big, big_farm, big_name = await farm_with(env, 'Большая', previous, 49300, now)
            small, _, _ = await farm_with(env, 'Малая', previous, 840, now)
            idle, _, _ = await farm_with(env, 'Тихая', previous, 0, now)
            async with env.db.transaction() as session:
                unit = Unit(session, env.schema)
                await unit.village_add(previous, 50140, now - 30 * DAY)
                assert await unit.village_top(previous) == dict(id=big_farm, name=big_name, personal=49300)
                assert await unit.village_top(season) is None

            async def shown(account):
                async with env.db.transaction() as session:
                    service = FarmService(Unit(session, env.schema), Principal(str(account), 'Игрок'), clock=lambda: now)
                    return (await service.view())['village']['previous']

            mine = await shown(big)
            assert mine['season'] == previous and mine['total'] == 50140 and not mine['reached']
            assert mine['personal'] == 49300 and mine['share_pct'] == 98
            assert mine['top'] == dict(name=big_name, personal=49300, own=True)
            other = await shown(small)
            assert other['personal'] == 840 and other['share_pct'] == 2
            assert other['top'] == dict(name=big_name, personal=49300, own=False)
            assert (await shown(idle))['personal'] == 0
    asyncio.run(scenario())


def test_no_summary_without_a_previous_season(pg_url):
    async def scenario():
        async with environment(pg_url) as env:
            now = 1_800_000_000
            account, _, _ = await farm_with(env, 'Игрок', economy.season_of(now) - 1, 0, now)
            async with env.db.transaction() as session:
                service = FarmService(Unit(session, env.schema), Principal(str(account), 'Игрок'), clock=lambda: now)
                assert (await service.view())['village']['previous'] is None
    asyncio.run(scenario())
