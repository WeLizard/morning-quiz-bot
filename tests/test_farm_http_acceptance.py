"""Host HTTP boundary checks for the PostgreSQL-backed Farm."""
import asyncio
from uuid import UUID

import pytest
from sqlalchemy import func, select

from storage.models import Account, SystemState
from tests.test_farm_platform import (
    API, FARM_HEADERS, environment, farm_pg_url, player, raw_farm, receipts,
)


def test_public_farm_page_does_not_start_a_profile(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env:
            page = await env.client.get('/app/farm')
            assert page.status_code == 200
            assert 'text/html' in page.headers['content-type']
            assert 'no-store' in page.headers['cache-control']
            assert "default-src 'none'" in page.headers['content-security-policy']
            assert (await env.client.get('/app/farm/assets/app.js')).status_code == 200
            config = await env.client.get(API + '/config')
            assert config.status_code == 200 and config.json()['server_owned'] is True
            assert (await env.client.get(API + '/me?identity=guest')).status_code == 401
            assert (await env.client.get(API + '/me?identity=telegram')).status_code == 401
            async with env.db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(Account)) == 0

    asyncio.run(run())


def test_both_cookies_require_explicit_identity_for_reads_and_writes(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env, player(env) as guest, player(env, 'telegram') as telegram:
            client = guest.client
            client.cookies.set('mqb_mini', telegram.client.cookies.get('mqb_mini'))
            for path in (API + '/me', API + '/invite'):
                ambiguous = await client.get(path)
                assert ambiguous.status_code == 401 and ambiguous.json()['code'] == 'identity_required'
            for identity, expected in (('guest', guest), ('telegram', telegram)):
                response = await client.get(API + '/me', params={'identity': identity})
                assert response.status_code == 200 and response.json()['farm']['id'] == expected.farm_id
            before = await raw_farm(env, guest)
            ambiguous = await client.post(API + '/commands', headers=FARM_HEADERS,
                json={'command_id': 'http-ambiguous', 'actor': guest.farm_id, 'kind': 'sell',
                      'target': guest.farm_id, 'data': {'item': 'wheat', 'qty': 1}})
            assert ambiguous.status_code == 401 and ambiguous.json()['code'] == 'identity_required'
            assert await raw_farm(env, guest) == before
            assert not await receipts(env, guest.account_id, 'http-ambiguous')

    asyncio.run(run())


@pytest.mark.parametrize('identity', ['guest', 'telegram'])
def test_invalid_and_expired_host_cookies_cannot_read_farm(farm_pg_url, identity):
    async def run():
        async with environment(farm_pg_url) as env, player(env, identity) as p:
            cookie_name = 'mqb_guest' if identity == 'guest' else 'mqb_mini'
            valid_cookie = p.client.cookies.get(cookie_name)
            before = await raw_farm(env, p)
            p.client.cookies.set(cookie_name, 'invalid-cookie')
            invalid = await p.client.get(API + '/me', params={'identity': identity})
            assert invalid.status_code == 401
            p.client.cookies.set(cookie_name, valid_cookie)
            env.now[0] += 31 * 24 * 60 * 60
            expired = await p.client.get(API + '/me', params={'identity': identity})
            assert expired.status_code == 401
            assert await raw_farm(env, p) == before

    asyncio.run(run())


@pytest.mark.parametrize('identity', ['guest', 'telegram'])
def test_maintenance_and_block_reject_farm_reads(farm_pg_url, identity):
    async def run():
        async with environment(farm_pg_url) as env, player(env, identity) as p:
            before = await raw_farm(env, p)
            async with env.db.transaction() as session:
                session.add(SystemState(key='maintenance_status', payload={'maintenance_mode': True}))
            maintenance = await p.client.get(API + '/me', params={'identity': identity})
            assert maintenance.status_code == 503 and maintenance.json()['code'] == 'maintenance'
            async with env.db.transaction() as session:
                (await session.get(SystemState, 'maintenance_status')).payload = {'maintenance_mode': False}
                (await session.get(Account, UUID(p.account_id))).bot_blocked = True
            blocked = await p.client.get(API + '/me', params={'identity': identity})
            assert blocked.status_code == 401
            assert await raw_farm(env, p) == before

    asyncio.run(run())
