"""Farm and Alchemy share an account without sharing game balances."""
import asyncio
import time
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from storage.models import Account, AlchemyProgress, User
from tests.test_farm_platform import (
    API, GUEST_HEADERS, MINI_HEADERS, accepted, environment,
    farm_pg_url, player, raw_farm,
)
from tests.test_mini_app import ORIGIN, TOKEN
from web.mini_app import MiniAppSettings, create_app


@pytest.mark.parametrize('identity', ['guest', 'telegram'])
def test_farm_and_alchemy_share_account_but_keep_progress_separate(farm_pg_url, identity):
    async def run():
        async with environment(farm_pg_url) as env:
            # Alchemy guest auth uses the wall clock; keep its session inside
            # the same validity window as the host's injected clock.
            env.now[0] = int(time.time())
            async with player(env, identity) as p:
                account_id = UUID(p.account_id)
                initial_farm = await raw_farm(env, p)
                alchemy_path = '/api/guest/alchemy' if identity == 'guest' else '/api/mini/alchemy'
                headers = ({**GUEST_HEADERS, 'X-Guest-Account': p.account_id}
                           if identity == 'guest' else {**MINI_HEADERS, 'X-Mini-User': str(p.user_id)})
                before = await p.client.get(alchemy_path)
                assert before.status_code == 200, before.text

                sold = await accepted(p, 'sell', {'item': 'wheat', 'qty': 1})
                assert sold['command_id']
                farm_after_sale = await raw_farm(env, p)
                assert farm_after_sale['coins'] > initial_farm['coins']
                assert farm_after_sale['inventory']['wheat'] == initial_farm['inventory']['wheat'] - 1
                alchemy_after_sale = await p.client.get(alchemy_path)
                assert alchemy_after_sale.status_code == 200
                assert alchemy_after_sale.json() == before.json()

                saved = await p.client.post(alchemy_path + '/sync', headers=headers,
                                            json={'discovered': ['steam'], 'attempts': 3})
                assert saved.status_code == 200, saved.text
                assert await raw_farm(env, p) == farm_after_sale

                async with env.db.transaction() as session:
                    account = await session.get(Account, account_id)
                    alchemy = await session.get(AlchemyProgress, account_id)
                    farm_table = env.schema['states']
                    farm_owner = await session.scalar(select(farm_table.c.account_id).where(
                        farm_table.c.id == UUID(p.farm_id)))
                    assert account is not None and farm_owner == account_id
                    assert alchemy is not None and alchemy.account_id == account_id
                    assert 'steam' in alchemy.discovered and alchemy.attempts == 3
                    assert alchemy.points_total == Decimal('0')
                    assert await session.scalar(select(func.count()).select_from(Account)) == 1
                    if identity == 'telegram':
                        user = await session.get(User, p.user_id)
                        assert user.account_id == account_id and alchemy.user_id == user.id
                        assert user.global_score == Decimal('0')
                    else:
                        assert alchemy.user_id is None
                        assert await session.scalar(select(func.count()).select_from(User)) == 0

                restarted = create_app(database=env.db,
                    settings=MiniAppSettings(TOKEN, ORIGIN, offline=True),
                    clock=lambda: env.now[0])
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted),
                                             base_url=ORIGIN, cookies=p.client.cookies) as resumed:
                    farm = await resumed.get(API + '/me', params={'identity': identity})
                    assert farm.status_code == 200, farm.text
                    assert farm.json()['farm']['id'] == p.farm_id
                    assert farm.json()['farm']['coins'] == farm_after_sale['coins']
                    progress = await resumed.get(alchemy_path)
                    assert progress.status_code == 200, progress.text
                    if identity == 'guest':
                        assert 'steam' in progress.json()['discovered']
                        profile = await resumed.get('/api/guest/me')
                        assert profile.status_code == 200
                        assert profile.json()['account_id'] == p.account_id
                    else:
                        assert progress.json()['discovered'] == before.json()['discovered'] + 1

    asyncio.run(run())
