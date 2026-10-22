"""PostgreSQL integration tests for Oleg's persisted run and daily reward."""
import asyncio
import os
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from qw_farm.catalog import LEVELS
from qw_farm.domain import new_farm
from qw_farm.expansion import upgrade_state
from qw_farm.integration import register_models
from qw_farm.persistence import Unit
from qw_farm.service import FarmService, Principal
from storage.database import normalize_database_url
from storage.models import Account
from tests.local_database import isolated_database


@asynccontextmanager
async def environment(url):
    schema = register_models()
    async with isolated_database(url) as (db, _):
        yield SimpleNamespace(db=db, schema=schema)


async def seeded(env, now):
    account_id = uuid4()
    async with env.db.transaction() as session:
        session.add(Account(id=account_id, display_name='Игрок'))
        await session.flush()
        farm = upgrade_state(new_farm(str(uuid4()), 'Игрок', now))
        farm['xp'] = LEVELS[2]
        unit = Unit(session, env.schema)
        await unit.save(farm, account_id)
    return account_id, farm['id']


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def pg_url(monkeypatch):
    raw = os.getenv('TEST_DATABASE_URL')
    if not raw:
        pytest.skip('TEST_DATABASE_URL is not configured')
    return normalize_database_url(raw)


def test_run_progress_and_daily_reward_persist_exactly_once(pg_url):
    async def scenario():
        async with environment(pg_url) as env:
            now = [1_800_000_000]
            account, _ = await seeded(env, now[0])
            async with env.db.transaction() as session:
                service = FarmService(Unit(session, env.schema), Principal(str(account), 'Игрок'), clock=lambda: now[0])
                started = await service.command('oleg-start-001', 'oleg_start', {})
                run_id = started['oleg_game']['active']['run_id']
                farm = await service.u.by_account(account)
                sequences = deepcopy(farm['oleg_game']['run']['sequences'])
                notes = None
                for number, sequence in enumerate(sequences):
                    notes = {'run_id': run_id, 'round': number, 'notes': sequence}
                    result = await service.command(f'oleg-answer-{number:02}', 'oleg_answer', notes)
                assert result['oleg_game']['active'] is None
                assert result['oleg_game']['last_result']['rewarded'] is True
                assert result['oleg_game']['rewarded_today'] is True
                completed = await service.u.by_account(account)
                assert completed["coins"] == 250 + 12 and completed['xp'] > LEVELS[2]
                revision, coins = result['revision'], completed['coins']
                replay = await service.command('oleg-answer-02', 'oleg_answer', notes)
                assert replay['revision'] == revision and replay['oleg_game']['active'] is None
                assert (await service.u.by_account(account))['coins'] == coins

            async with env.db.transaction() as session:
                unit = Unit(session, env.schema)
                stored = await unit.by_account(account)
                assert stored['oleg_game']['run'] is None and stored['oleg_game']['reward_day'] >= 0
                assert stored['coins'] == coins
                service = FarmService(unit, Principal(str(account), 'Игрок'), clock=lambda: now[0])
                again = await service.command('oleg-start-002', 'oleg_start', {})
                second_run = again['oleg_game']['active']['run_id']
                sequences = deepcopy((await service.u.by_account(account))['oleg_game']['run']['sequences'])
                for number, sequence in enumerate(sequences):
                    result = await service.command(f'oleg-again-{number:02}', 'oleg_answer',
                                                   {'run_id': second_run, 'round': number, 'notes': sequence})
                assert result['oleg_game']['last_result']['rewarded'] is False
                assert (await service.u.by_account(account))['coins'] == coins
    run(scenario())
