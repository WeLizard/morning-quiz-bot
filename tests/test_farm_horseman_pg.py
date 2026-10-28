"""Persisted Pumpkin Night gift: receipt, ledger and concurrent commands."""

import asyncio
import os
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from qw_farm.domain import FarmError
from qw_farm.persistence import Unit
from qw_farm.service import FarmService, Principal
from storage.database import normalize_database_url
from tests.test_farm_oleg_pg import environment, seeded
from tests.test_farm_horseman import ts
from tests.test_farm_platform import FARM_HEADERS, accepted, command, environment as http_environment, farm_pg_url, player, view  # noqa: F401


@pytest.fixture
def pg_url():
    raw = os.getenv('TEST_DATABASE_URL')
    if not raw:
        pytest.skip('TEST_DATABASE_URL is not configured')
    return normalize_database_url(raw)


def test_concurrent_ids_give_one_gift_and_one_ledger_entry(pg_url):
    async def scenario():
        async with environment(pg_url) as env:
            at = ts(10, 26, 18)
            account, farm_id = await seeded(env, at)

            async def issue(key):
                async with env.db.transaction() as session:
                    service = FarmService(Unit(session, env.schema), Principal(str(account), 'Игрок'), clock=lambda: at)
                    try:
                        return await service.command(key, 'claim_horseman_gift', {})
                    except FarmError as exc:
                        return exc.code

            keys = [str(uuid4()), str(uuid4())]
            outcomes = await asyncio.gather(*(issue(key) for key in keys))
            successes = [value for value in outcomes if isinstance(value, dict)]
            assert len(successes) == 1
            assert 'horseman_claimed' in outcomes
            winner = successes[0]['command_id']
            assert await issue(winner) == successes[0]

            async with env.db.transaction() as session:
                unit = Unit(session, env.schema)
                stored = await unit.get(farm_id)
                assert stored['inventory']['pumpkin_candy'] == 3
                assert 'horseman_gifts' in stored
                rows = (await unit.execute(sa.select(unit.t['ledger']).where(
                    unit.t['ledger'].c.farm_id == UUID(farm_id),
                    unit.t['ledger'].c.kind == 'claim_horseman_gift'))).mappings().all()
                assert len(rows) == 1
                assert rows[0]['command_id'] == winner
                assert rows[0]['coins_delta'] == rows[0]['xp_delta'] == 0
                assert rows[0]['inventory_delta'] == {'pumpkin_candy': 3, 'wheat': 4}
    asyncio.run(scenario())


def test_http_start_claim_me_and_reject_repeat(farm_pg_url):
    async def scenario():
        async with http_environment(farm_pg_url) as env:
            env.now[0] = ts(10, 26, 18)
            async with player(env) as owner:
                start = await owner.client.post('/api/farm/v1/start', params={'identity': owner.identity},
                                                headers=FARM_HEADERS)
                assert start.status_code == 200, start.text
                assert start.json()['farm']['horseman']['can_claim']
                first = await accepted(owner, 'claim_horseman_gift', {})
                assert first['notice']
                shown = await view(owner)
                assert shown['horseman']['claimed_today'] and shown['horseman']['active']
                assert shown['inventory']['pumpkin_candy'] == 3
                retry = await command(owner, 'claim_horseman_gift', {})
                assert retry.status_code == 409 and retry.json()['code'] == 'horseman_claimed'
                assert (await view(owner))['inventory']['pumpkin_candy'] == 3
    asyncio.run(scenario())
