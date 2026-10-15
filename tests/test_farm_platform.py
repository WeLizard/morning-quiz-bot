"""Farm 0.2.0 acceptance through host auth and real PostgreSQL transactions.

Only TEST_DATABASE_URL is accepted. Each scenario owns an isolated schema;
neither the demo SQLite backend nor production/dev data are used.
"""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import os
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from qw_farm.domain import validate_state
from qw_farm.integration import register_models
from qw_farm.invites import NEIGHBOR
from qw_farm.persistence import Unit
from storage.admin_actions import operation_fence
from storage.database import normalize_database_url
from storage.guest_accounts import credential_hash
from storage.mini_app import token_digest
from storage.models import Account, GuestSession, MiniAppSession, SystemState, User
from tests.local_database import isolated_database
from tests.test_mini_app import NOW, ORIGIN, TOKEN, signed
from web.mini_app import MiniAppSettings, create_app

FARM_HEADERS = {'Origin': ORIGIN, 'X-QW-Farm': '1'}
GUEST_HEADERS = {'Origin': ORIGIN, 'X-Guest-CSRF': '1'}
MINI_HEADERS = {'Origin': ORIGIN, 'X-Mini-CSRF': '1'}
API = '/api/farm/v1'


@pytest.fixture
def farm_pg_url(monkeypatch):
    raw = os.getenv('TEST_DATABASE_URL')
    if not raw:
        pytest.skip('TEST_DATABASE_URL unset; real PostgreSQL acceptance not executed')
    url = normalize_database_url(raw)
    parsed = make_url(url)
    if parsed.drivername != 'postgresql+asyncpg' or parsed.database != 'morning_quiz_test':
        pytest.fail('Farm acceptance requires PostgreSQL morning_quiz_test')
    # isolated_database additionally verifies the local endpoint/user before DDL.
    monkeypatch.setenv('QW_FARM_ENABLED', '1')
    return url


@asynccontextmanager
async def environment(url, *, allowed_user_ids=None):
    schema = register_models()
    async with isolated_database(url) as (db, _):
        now = [NOW]
        app = create_app(database=db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True),
                         clock=lambda: now[0], allowed_user_ids=allowed_user_ids)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            yield SimpleNamespace(db=db, app=app, client=client, now=now, schema=schema)


@asynccontextmanager
async def player(env, identity='guest', user_id=981020000001, invite=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url=ORIGIN) as client:
        if identity == 'guest':
            response = await client.post('/api/guest/start', headers=GUEST_HEADERS)
            assert response.status_code == 200, response.text
            account_id = response.json()['account_id']
        else:
            account_id = str(uuid4())
            async with env.db.transaction() as session:
                session.add(Account(id=UUID(account_id), display_name='PG Telegram'))
                await session.flush()
                session.add(User(id=user_id, account_id=UUID(account_id), display_name='PG Telegram'))
            response = await client.post('/api/mini/session', json={
                'init_data': signed(user_id, date=env.now[0], query_id=uuid4().hex)})
            assert response.status_code == 200, response.text
        response = await client.post(API + '/start', params={'identity': identity}, headers=FARM_HEADERS,
                                     **({'json': {'invite': invite}} if invite else {}))
        assert response.status_code == 200, response.text
        assert response.json()['identity'] == identity
        yield SimpleNamespace(client=client, identity=identity, account_id=account_id,
                              farm_id=response.json()['farm']['id'], user_id=user_id)


async def command(p, kind, data, *, target=None, key=None, actor=None):
    return await p.client.post(API + '/commands', params={'identity': p.identity},
        headers=FARM_HEADERS, json={'command_id': key or str(uuid4()), 'actor': actor or p.farm_id,
                                  'kind': kind, 'target': target or p.farm_id, 'data': data})


async def accepted(p, kind, data, **kwargs):
    response = await command(p, kind, data, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()


async def view(p, target=None):
    path = '/farms/' + target if target else '/me'
    response = await p.client.get(API + path, params={'identity': p.identity})
    assert response.status_code == 200, response.text
    return response.json()['farm']


async def raw_farm(env, p):
    async with env.db.transaction() as session:
        return await Unit(session, env.schema).by_account(p.account_id)


async def seed_economy(env, p, *, clear_crops=False):
    """Fixture-only eligibility; gameplay assertions still run through HTTP."""
    async with env.db.transaction() as session:
        unit = Unit(session, env.schema)
        farm = await unit.by_account(p.account_id)
        before = deepcopy(farm)
        farm.update(coins=1000, xp=10000)
        farm['stats']['orders'] = 3
        if clear_crops:
            for obj in farm['objects']:
                if obj['type'] == 'plot':
                    obj['crop'] = None
        validate_state(farm)
        await unit.save(farm)
        await unit.record(p.account_id, 'fixture-economy', 'fixture', before, farm, env.now[0])


async def be_neighbors(a, b):
    await accepted(a, 'request_neighbor', {}, target=b.farm_id)
    await accepted(b, 'accept_neighbor', {}, target=a.farm_id)


async def receipts(env, account_id, key):
    async with env.db.transaction() as session:
        table = env.schema['receipts']
        return (await session.execute(select(table).where(
            table.c.account_id == UUID(account_id), table.c.command_id == key))).mappings().all()


async def ledger(env, *, key=None):
    async with env.db.transaction() as session:
        table = env.schema['ledger']
        statement = select(table)
        if key is not None:
            statement = statement.where(table.c.command_id == key)
        return (await session.execute(statement)).mappings().all()


def test_identity_selection_stale_actor_and_lost_command_response(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env, player(env) as guest, player(env, 'telegram') as telegram:
            client = guest.client
            client.cookies.set('mqb_mini', telegram.client.cookies.get('mqb_mini'))
            ambiguous = await client.post(API + '/start', headers=FARM_HEADERS)
            assert ambiguous.status_code == 401 and ambiguous.json()['code'] == 'identity_required'
            own = await client.post(API + '/start?identity=guest', headers=FARM_HEADERS)
            other = await client.post(API + '/start?identity=telegram', headers=FARM_HEADERS)
            assert own.json()['farm']['id'] == guest.farm_id
            assert other.json()['farm']['id'] == telegram.farm_id != guest.farm_id
            assert own.json()['identity'] == 'guest' and other.json()['identity'] == 'telegram'
            before = await raw_farm(env, telegram)
            stale = SimpleNamespace(client=client, identity='telegram', farm_id=telegram.farm_id)
            response = await command(stale, 'sell', {'item': 'wheat', 'qty': 1},
                                     actor=guest.farm_id, key='pg-stale-actor')
            assert response.status_code == 409 and response.json()['code'] == 'profile_changed'
            assert await raw_farm(env, telegram) == before
            assert not await receipts(env, telegram.account_id, 'pg-stale-actor')

            before = await raw_farm(env, guest)
            key = 'pg-lost-sell-response'
            # The first HTTP result is deliberately discarded, like a lost response.
            await accepted(guest, 'sell', {'item': 'wheat', 'qty': 2}, key=key)
            after = await raw_farm(env, guest)
            retry = await accepted(guest, 'sell', {'item': 'wheat', 'qty': 2}, key=key)
            assert await raw_farm(env, guest) == after
            stored = await receipts(env, guest.account_id, key)
            assert len(stored) == 1 and stored[0]['result'] == retry
            assert set(retry) == {'command_id', 'notice', 'server_time', 'revision'}
            entries = await ledger(env, key=key)
            assert len(entries) == 1 and entries[0]['inventory_delta'] == {'wheat': -2}
            assert after['coins'] == before['coins'] + entries[0]['coins_delta']
            assert after['inventory']['wheat'] == before['inventory']['wheat'] - 2
            reused = await command(guest, 'sell', {'item': 'wheat', 'qty': 1}, key=key)
            assert reused.status_code == 409 and reused.json()['code'] == 'key_reused'
            assert await raw_farm(env, guest) == after
            async with env.db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(Account)) == 2
                assert await session.scalar(select(func.count()).select_from(User)) == 1
    asyncio.run(run())


@pytest.mark.parametrize('identity', ['guest', 'telegram'])
def test_session_renewal_and_expiry(farm_pg_url, identity):
    async def run():
        async with environment(farm_pg_url) as env, player(env, identity) as p:
            cookie_name = 'mqb_guest' if identity == 'guest' else 'mqb_mini'
            raw = p.client.cookies.get(cookie_name)
            table = GuestSession if identity == 'guest' else MiniAppSession
            digest = credential_hash(raw) if identity == 'guest' else token_digest(raw)
            endpoint = '/api/guest/resume' if identity == 'guest' else '/api/mini/session/renew'
            headers = GUEST_HEADERS if identity == 'guest' else MINI_HEADERS
            async with env.db.transaction() as session:
                before_expiry = (await session.get(table, digest)).expires_at
            env.now[0] += 60
            for _ in range(2):
                response = await p.client.post(endpoint, headers=headers)
                assert response.status_code == 200, response.text
                assert p.client.cookies.get(cookie_name) == raw
            async with env.db.transaction() as session:
                expires = (await session.get(table, digest)).expires_at
                assert expires > before_expiry
                assert await session.scalar(select(func.count()).select_from(table)) == 1
            assert (await view(p))['id'] == p.farm_id
            env.now[0] = int(expires.timestamp()) + 61
            before = await raw_farm(env, p)
            response = await command(p, 'sell', {'item': 'wheat', 'qty': 1}, key='pg-expired-session')
            assert response.status_code == 401
            assert (await p.client.post(endpoint, headers=headers)).status_code == 401
            assert await raw_farm(env, p) == before
            assert not await receipts(env, p.account_id, 'pg-expired-session')
    asyncio.run(run())


@pytest.mark.parametrize('identity', ['guest', 'telegram'])
def test_maintenance_and_account_block_roll_back_commands(farm_pg_url, identity):
    async def run():
        async with environment(farm_pg_url) as env, player(env, identity) as p:
            before = await raw_farm(env, p)
            async with env.db.transaction() as session:
                session.add(SystemState(key='maintenance_status', payload={'maintenance_mode': True}))
            response = await command(p, 'sell', {'item': 'wheat', 'qty': 1}, key='pg-maintenance')
            assert response.status_code == 503 and response.json()['code'] == 'maintenance'
            assert await raw_farm(env, p) == before
            assert not await receipts(env, p.account_id, 'pg-maintenance')
            assert not await ledger(env, key='pg-maintenance')
            async with env.db.transaction() as session:
                row = await session.get(SystemState, 'maintenance_status')
                row.payload = {'maintenance_mode': False}
                account = await session.get(Account, UUID(p.account_id))
                account.bot_blocked = True
            response = await command(p, 'sell', {'item': 'wheat', 'qty': 1}, key='pg-blocked')
            assert response.status_code == 401
            assert await raw_farm(env, p) == before
            assert not await receipts(env, p.account_id, 'pg-blocked')
            assert not await ledger(env, key='pg-blocked')
    asyncio.run(run())


@pytest.mark.parametrize('identity', ['guest', 'telegram'])
@pytest.mark.parametrize('moderation', ['maintenance', 'block'])
def test_administrative_fence_wins_against_waiting_command(farm_pg_url, monkeypatch, identity, moderation):
    async def run():
        entered = asyncio.Event()
        observing = False

        async def observed_fence(session, *, exclusive=False):
            if observing and not exclusive:
                entered.set()
            await operation_fence(session, exclusive=exclusive)

        # Observe scheduling without replacing actual PG fence/account locks.
        monkeypatch.setattr('storage.admin_actions.operation_fence', observed_fence)
        monkeypatch.setattr('storage.mini_app.operation_fence', observed_fence)
        async with environment(farm_pg_url) as env, player(env, identity) as p:
            before = await raw_farm(env, p)
            task = None
            try:
                async with env.db.transaction() as session:
                    await operation_fence(session, exclusive=True)
                    if moderation == 'maintenance':
                        session.add(SystemState(key='maintenance_status', payload={'maintenance_mode': True}))
                    else:
                        account = await session.get(Account, UUID(p.account_id))
                        account.bot_blocked = True
                    observing = True
                    task = asyncio.create_task(command(p, 'sell', {'item': 'wheat', 'qty': 1}, key='pg-fence-race'))
                    await asyncio.wait_for(entered.wait(), timeout=5)
                    assert not task.done()
                response = await asyncio.wait_for(task, timeout=10)
                assert response.status_code == (503 if moderation == 'maintenance' else 401)
                assert await raw_farm(env, p) == before
                assert not await receipts(env, p.account_id, 'pg-fence-race')
                assert not await ledger(env, key='pg-fence-race')
            finally:
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_two_buyers_one_listing_preserve_balance_and_receipts(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env, player(env) as seller, player(env) as a, player(env) as b:
            for p in (seller, a, b):
                await seed_economy(env, p)
            await be_neighbors(seller, a)
            await be_neighbors(seller, b)
            listing = 'pg-single-listing'
            await accepted(seller, 'list', {'item': 'wheat', 'qty': 3, 'unit_price': 4}, key=listing)
            responses = await asyncio.wait_for(asyncio.gather(
                command(a, 'buy', {'listing': listing}, target=seller.farm_id, key='pg-buyer-a'),
                command(b, 'buy', {'listing': listing}, target=seller.farm_id.upper(), key='pg-buyer-b'),
            ), timeout=10)
            # The losing buyer sees the listing as gone (non-disclosing 404),
            # not a balance-changing conflict.
            assert sorted(r.status_code for r in responses) == [200, 404]
            farms = [await raw_farm(env, p) for p in (seller, a, b)]
            assert not farms[0]['listings']
            reward = NEIGHBOR['reward']  # being neighbours pays both sides once: the seller met two buyers
            assert [f['coins'] for f in farms] in ([1011 + 2 * reward, 988 + reward, 1000 + reward],
                                                   [1011 + 2 * reward, 1000 + reward, 988 + reward])
            assert sum(f['coins'] for f in farms) == 2999 + 4 * reward  # 12 total, one coin fee; four neighbour rewards
            assert farms[0]['inventory']['wheat'] == 3
            assert sorted(f['inventory']['wheat'] for f in farms[1:]) == [6, 9]
            for p, response, key in zip((a, b), responses, ('pg-buyer-a', 'pg-buyer-b')):
                stored = await receipts(env, p.account_id, key)
                entries = await ledger(env, key=key)
                if response.status_code == 200:
                    assert len(stored) == 1 and stored[0]['result'] == response.json()
                    assert len(entries) == 2 and sum(row['coins_delta'] for row in entries) == -1
                    assert sum(row['inventory_delta'].get('wheat', 0) for row in entries) == 3
                    assert await accepted(p, 'buy', {'listing': listing}, target=seller.farm_id, key=key) == response.json()
                else:
                    assert not stored and not entries
    asyncio.run(run())


@pytest.mark.parametrize('identities', [('guest', 'guest'), ('telegram', 'telegram'), ('guest', 'telegram')])
def test_reciprocal_visits_settle_automation_without_account_lock_deadlock(farm_pg_url, monkeypatch, identities):
    async def run():
        async with environment(farm_pg_url) as env, player(env, identities[0], 981020000011) as a, player(env, identities[1], 981020000012) as b:
            await be_neighbors(a, b)
            for p in (a, b):
                await seed_economy(env, p, clear_crops=True)
                await accepted(p, 'buy_equipment', {'equipment': 'robot'})
                await accepted(p, 'plant', {'object': 'plot_3', 'crop': 'wheat', 'revision': 0})
                await accepted(p, 'start_shift', {'worker': 'robot', 'shift': 'short'})
            before = [await raw_farm(env, p) for p in (a, b)]
            env.now[0] += 61
            barrier = asyncio.Barrier(2)
            original_lock = Unit.lock

            async def rendezvous(unit, *keys):
                # Schedule only: real host authentication has already acquired
                # both accounts before either request takes sorted farm locks.
                if len(keys) == 2 and all(key.startswith('farm:') for key in keys):
                    await barrier.wait()
                return await original_lock(unit, *keys)

            with monkeypatch.context() as patch:
                patch.setattr(Unit, 'lock', rendezvous)
                results = await asyncio.wait_for(asyncio.gather(view(a, b.farm_id), view(b, a.farm_id)), timeout=10)
            for projection in results:
                assert 'coins' not in projection and 'inventory' not in projection
                assert 'trips' not in projection
            after = [await raw_farm(env, p) for p in (a, b)]
            for old, new in zip(before, after):
                assert new['coins'] == old['coins'] == 554
                assert new['inventory']['wheat'] == old['inventory']['wheat'] + 3
                assert new['xp'] == old['xp'] + 1
                assert new['stats']['automation'] == 1
                assert new['equipment']['robot']['shift']['done'] == 1
            entries = [row for row in await ledger(env) if row['kind'] == 'automation']
            assert len(entries) == 2
            assert {str(row['actor_account_id']) for row in entries} == {a.account_id, b.account_id}
            assert all(row['inventory_delta'] == {'wheat': 3} and row['coins_delta'] == 0 for row in entries)
            # Concurrent owner refreshes cannot harvest the same crop again.
            await asyncio.wait_for(asyncio.gather(view(a), view(a), view(b), view(b)), timeout=10)
            assert [await raw_farm(env, p) for p in (a, b)] == after
            assert len([row for row in await ledger(env) if row['kind'] == 'automation']) == 2
    asyncio.run(run())


def test_concurrent_basket_claim_and_lost_response_award_once(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env, player(env) as p:
            await accepted(p, 'start_trip', {'route': 'mushroom_wood', 'guide': ''}, key='pg-trip-start')
            before = await raw_farm(env, p)
            env.now[0] += 301
            key = 'pg-basket-claim'
            results = await asyncio.wait_for(asyncio.gather(*(
                command(p, 'collect_trip', {'trip': 'pg-trip-start'}, key=key) for _ in range(4))), timeout=10)
            assert all(r.status_code == 200 and r.json() == results[0].json() for r in results)
            after = await raw_farm(env, p)
            assert after['inventory'].get('mushroom', 0) == 3
            assert after['inventory'].get('chanterelle', 0) == 1
            assert after['coins'] == before['coins'] == 246
            assert after['xp'] == before['xp'] + 16 and not after['trips']  # 8 base XP x2: Morning dew (M1)
            assert after['stats']['forages'] == 1
            assert len(await receipts(env, p.account_id, key)) == 1
            entries = await ledger(env, key=key)
            assert len(entries) == 1 and entries[0]['inventory_delta'] == {'mushroom': 3, 'chanterelle': 1}
            assert entries[0]['coins_delta'] == 0 and entries[0]['xp_delta'] == 16
            assert await accepted(p, 'collect_trip', {'trip': 'pg-trip-start'}, key=key) == results[0].json()
            assert await raw_farm(env, p) == after
    asyncio.run(run())
