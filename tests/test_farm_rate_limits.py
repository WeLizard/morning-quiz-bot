"""Shared Farm quotas through independent ASGI apps and real disposable PG."""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import replace
from datetime import timedelta
import time

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from qw_farm.rate_limits import RateSettings, SharedRateLimits, normalized_ip
from qw_farm.service import FarmService
from storage.database import Database, DatabaseSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.dialects.postgresql import Insert
from storage.models import Account
from tests.test_farm_platform import (
    API, FARM_HEADERS, farm_pg_url, environment, player, command, raw_farm, receipts,
)
from tests.test_mini_app import ORIGIN, TOKEN
from web.mini_app import MiniAppSettings, create_app


@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setenv('QW_FARM_SHARED_RATE_ENABLED', '1')
    monkeypatch.setenv('QW_FARM_RATE_SECRET', 'test-only-shared-farm-secret-00000001')


@asynccontextmanager
async def peer(env, *, app=None, ip='127.0.0.2', cookie=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app or env.app,
        client=(ip, 12345)), base_url=ORIGIN) as client:
        if cookie:
            client.cookies.set('mqb_guest', cookie)
        yield client


def another_app(env):
    return create_app(database=env.db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True),
                      clock=lambda: env.now[0])


async def buckets(env, scope=None):
    table = env.app.state.farm_shared_rate.table
    async with env.db.transaction() as session:
        query = select(table)
        if scope:
            query = query.where(table.c.scope == scope)
        return (await session.execute(query)).mappings().all()


def test_config_requires_separate_secret_and_bounded_limits(monkeypatch):
    for secret in ('', 'short'):
        with pytest.raises(ValueError):
            RateSettings(secret)
    with pytest.raises(ValueError):
        RateSettings('x' * 32, ip_read=0)
    with pytest.raises(ValueError):
        RateSettings('x' * 32, account_read=10001)
    monkeypatch.setenv('QW_FARM_ENABLED', '1')
    monkeypatch.setenv('QW_FARM_SHARED_RATE_ENABLED', '1')
    monkeypatch.setenv('QW_FARM_RATE_SECRET', TOKEN)
    with pytest.raises(ValueError, match='must not reuse'):
        create_app(database=object(), settings=MiniAppSettings(TOKEN, ORIGIN, offline=True))
    assert normalized_ip(type('R', (), {'client': type('C', (), {'host': '::ffff:127.0.0.1'})()})()) == '127.0.0.1'


def test_two_apps_share_ip_budget_and_ignore_spoofed_forwarding(farm_pg_url, shared):
    async def run():
        async with environment(farm_pg_url) as env:
            second = another_app(env)
            for app in (env.app, second):
                app.state.farm_shared_rate.settings = replace(app.state.farm_shared_rate.settings, ip_read=3)
            async with peer(env) as a, peer(env, app=second) as b:
                responses = await asyncio.gather(*(
                    (a if i % 2 else b).get(API + '/config', headers={'X-Forwarded-For': f'192.0.2.{i}'})
                    for i in range(8)))
                assert sorted(r.status_code for r in responses) == [200] * 3 + [429] * 5
                for response in responses:
                    if response.status_code == 429:
                        assert 1 <= int(response.headers['retry-after']) <= 60
                        assert response.headers['cache-control'] == 'no-store'
                stored = await buckets(env, 'ip_read')
                assert len(stored) == 1 and len(stored[0]['timestamps']) == 3
                assert stored[0]['subject'] == env.app.state.farm_shared_rate.subject('ip_read', '127.0.0.2')
    asyncio.run(run())


@pytest.mark.parametrize('identity', ['guest', 'telegram'])
def test_account_budget_survives_worker_and_ip_change(farm_pg_url, shared, identity):
    async def run():
        async with environment(farm_pg_url) as env, player(env, identity) as p:
            second = another_app(env)
            for app in (env.app, second):
                app.state.farm_shared_rate.settings = replace(app.state.farm_shared_rate.settings, account_read=2)
            async with peer(env) as a, peer(env, app=second, ip='127.0.0.3') as b:
                name = 'mqb_guest' if identity == 'guest' else 'mqb_mini'
                for client in (a, b):
                    client.cookies.set(name, p.client.cookies.get(name))
                responses = await asyncio.gather(*(
                    (a if i % 2 else b).get(API + '/me', params={'identity': identity}) for i in range(6)))
                assert sorted(r.status_code for r in responses) == [200, 200, 429, 429, 429, 429]
                stored = await buckets(env, 'account_read')
                assert len(stored) == 1 and len(stored[0]['timestamps']) == 2
                assert stored[0]['subject'] == env.app.state.farm_shared_rate.subject('account_read', p.account_id)
    asyncio.run(run())


def test_nat_accounts_and_read_write_budgets_are_independent(farm_pg_url, shared):
    async def run():
        async with environment(farm_pg_url) as env, player(env) as a, player(env) as b:
            limiter = env.app.state.farm_shared_rate
            limiter.settings = replace(limiter.settings, account_read=1)
            assert (await a.client.get(API + '/me?identity=guest')).status_code == 200
            assert (await a.client.get(API + '/me?identity=guest')).status_code == 429
            assert (await b.client.get(API + '/me?identity=guest')).status_code == 200
            assert (await command(a, 'sell', {'item': 'wheat', 'qty': 1})).status_code == 200
            assert (await command(b, 'sell', {'item': 'wheat', 'qty': 1})).status_code == 200
            assert len(await buckets(env, 'account_read')) == 2
            assert len(await buckets(env, 'ip_read')) == 1
            assert len(await buckets(env, 'ip_write')) == 1
    asyncio.run(run())


def test_origin_csrf_fetch_site_reject_before_quota_and_auth_failure_only_costs_ip(farm_pg_url, shared):
    async def run():
        async with environment(farm_pg_url) as env:
            assert (await env.client.post(API + '/start')).status_code == 403
            assert (await env.client.post(API + '/start', headers={**FARM_HEADERS, 'Origin': 'https://evil.invalid'})).status_code == 403
            assert (await env.client.get(API + '/me', headers={'Sec-Fetch-Site': 'cross-site'})).status_code == 403
            assert not await buckets(env)
            assert (await env.client.get(API + '/me?identity=guest')).status_code == 401
            assert len(await buckets(env, 'ip_read')) == 1
            assert not await buckets(env, 'account_read')
    asyncio.run(run())


def test_expiry_precise_retry_and_cleanup_are_bounded(farm_pg_url, shared):
    async def run():
        async with environment(farm_pg_url) as env:
            limiter = env.app.state.farm_shared_rate
            limiter.settings = replace(limiter.settings, ip_read=1)
            assert (await env.client.get(API + '/config')).status_code == 200
            async with env.db.transaction() as session:
                now = await session.scalar(select(func.clock_timestamp()))
                await session.execute(update(limiter.table).values(timestamps=[now.timestamp() - 55],
                    expires_at=now + timedelta(seconds=5)))
            response = await env.client.get(API + '/config')
            assert response.status_code == 429 and 1 <= int(response.headers['retry-after']) <= 5
            async with env.db.transaction() as session:
                now = await session.scalar(select(func.clock_timestamp()))
                await session.execute(update(limiter.table).values(timestamps=[now.timestamp() - 61],
                    expires_at=now - timedelta(seconds=1)))
                await session.execute(limiter.table.insert(), [dict(scope='ip_write', subject=f'{i:064x}',
                    timestamps=[], expires_at=now - timedelta(seconds=1)) for i in range(150)])
            limiter.next_cleanup = 0
            assert (await env.client.get(API + '/config')).status_code == 200
            assert len(await buckets(env)) == 52  # at most 100 of 151 expired, plus recreated read bucket
            assert (await env.client.get(API + '/config')).status_code == 429
            assert len(await buckets(env)) == 52  # cleanup interval prevents repeated scans
    asyncio.run(run())


def test_rejected_ingress_commits_expired_bucket_cleanup(farm_pg_url, shared):
    async def run():
        async with environment(farm_pg_url) as env:
            limiter = env.app.state.farm_shared_rate
            limiter.settings = replace(limiter.settings, ip_read=1)
            assert (await env.client.get(API + '/config')).status_code == 200
            async with env.db.transaction() as session:
                now = await session.scalar(select(func.clock_timestamp()))
                await session.execute(limiter.table.insert(), [dict(scope='ip_write', subject=f'{i:064x}',
                    timestamps=[], expires_at=now - timedelta(seconds=1)) for i in range(150)])
            limiter.next_cleanup = 0
            assert (await env.client.get(API + '/config')).status_code == 429
            assert len(await buckets(env)) == 51
            assert (await env.client.get(API + '/config')).status_code == 429
            assert len(await buckets(env)) == 51
            assert len((await buckets(env, 'ip_read'))[0]['timestamps']) == 1
    asyncio.run(run())


def test_cleanup_cannot_delete_bucket_between_conflict_upsert_and_lock(farm_pg_url, shared, monkeypatch):
    async def run():
        async with environment(farm_pg_url) as env:
            limiter = env.app.state.farm_shared_rate
            cleaner = SharedRateLimits(env.db, limiter.table, limiter.settings)
            subject = limiter.subject('ip_read', '127.0.0.2')
            async with env.db.transaction() as session:
                now = await session.scalar(select(func.clock_timestamp()))
                await session.execute(limiter.table.insert().values(scope='ip_read', subject=subject,
                    timestamps=[now.timestamp() - 61], expires_at=now - timedelta(seconds=1)))
            limiter.next_cleanup = time.monotonic() + 60
            entered, resume = asyncio.Event(), asyncio.Event()
            pause = ContextVar('pause_farm_quota_upsert', default=False)
            original = AsyncSession.execute
            async def execute(session, statement, *args, **kwargs):
                result = await original(session, statement, *args, **kwargs)
                if pause.get() and isinstance(statement, Insert) and statement.table.name == 'farm_rate_buckets':
                    entered.set()
                    await resume.wait()
                return result
            async def request():
                pause.set(True)
                async with peer(env) as client:
                    return await client.get(API + '/config')
            with monkeypatch.context() as patch:
                patch.setattr(AsyncSession, 'execute', execute)
                task = asyncio.create_task(request())
                try:
                    await asyncio.wait_for(entered.wait(), 2)
                    async with env.db.transaction() as session:
                        await cleaner.cleanup_in(session)
                        assert await session.scalar(select(func.count()).select_from(limiter.table)) == 1
                    resume.set()
                    response = await asyncio.wait_for(task, 3)
                    assert response.status_code == 200, response.text
                finally:
                    resume.set()
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            stored = await buckets(env, 'ip_read')
            assert len(stored) == 1 and len(stored[0]['timestamps']) == 1
    asyncio.run(run())


def test_command_errors_rollback_and_replay_still_consume_quota(farm_pg_url, shared, monkeypatch):
    async def run():
        async with environment(farm_pg_url) as env, player(env) as p:
            before = await raw_farm(env, p)
            failed = await command(p, 'sell', {'item': 'wheat', 'qty': 99}, key='quota-invalid')
            assert failed.status_code == 409 and await raw_farm(env, p) == before
            key = 'quota-replay'
            ok = await command(p, 'sell', {'item': 'wheat', 'qty': 1}, key=key)
            replay = await command(p, 'sell', {'item': 'wheat', 'qty': 1}, key=key)
            assert replay.status_code == ok.status_code == 200 and replay.json() == ok.json()
            assert len(await receipts(env, p.account_id, key)) == 1
            settled = await raw_farm(env, p)
            original = FarmService.command
            async def broken(service, *args, **kwargs):
                await original(service, *args, **kwargs)
                raise OperationalError('fixture', {}, RuntimeError('fixture outage'))
            with monkeypatch.context() as patch:
                patch.setattr(FarmService, 'command', broken)
                failed = await command(p, 'sell', {'item': 'wheat', 'qty': 1}, key='quota-rollback')
                assert failed.status_code == 503
            assert not await receipts(env, p.account_id, 'quota-rollback')
            assert await raw_farm(env, p) == settled
            stored = await buckets(env, 'account_write')
            assert len(stored[0]['timestamps']) == 5  # start, invalid, accepted, replay, rolled back
    asyncio.run(run())


def test_db_outage_and_missing_schema_fail_closed(farm_pg_url, shared, monkeypatch):
    async def run():
        async with environment(farm_pg_url) as env:
            limiter = env.app.state.farm_shared_rate
            await limiter.check_schema()
            async def outage(*args, **kwargs):
                raise OperationalError('fixture', {}, RuntimeError('fixture unavailable'))
            with monkeypatch.context() as patch:
                patch.setattr(limiter, 'consume_in', outage)
                response = await env.client.get(API + '/config')
                assert response.status_code == 503 and response.json()['code'] == 'rate_unavailable'
                assert response.headers['cache-control'] == 'no-store'
                assert not await buckets(env)
                with pytest.raises(RuntimeError, match='schema is unavailable'):
                    # Exercise real missing-table detection via an isolated nonexistent table.
                    from sqlalchemy import MetaData
                    from qw_farm.rate_limits import rate_table
                    missing = rate_table(MetaData(schema='missing_farm_quota_schema'))
                    patch.setattr(limiter, 'table', missing)
                    await limiter.check_schema()
                with pytest.raises(RuntimeError, match='schema is unavailable'):
                    async with env.app.router.lifespan_context(env.app):
                        pass
                patch.setattr(limiter, 'consume_in', type(limiter).consume_in.__get__(limiter))
                response = await env.client.get(API + '/config')
                assert response.status_code == 503 and response.json()['code'] == 'rate_unavailable'
    asyncio.run(run())


def test_account_preflight_outage_or_timeout_never_enters_game(farm_pg_url, shared, monkeypatch):
    async def run():
        async with environment(farm_pg_url) as env, player(env) as p:
            limiter = env.app.state.farm_shared_rate
            original = limiter.consume_in
            before = await raw_farm(env, p)
            for error in (OperationalError('fixture', {}, RuntimeError()), TimeoutError()):
                async def outage(session, scope, value):
                    if scope.startswith('account_'):
                        raise error
                    await original(session, scope, value)
                with monkeypatch.context() as patch:
                    patch.setattr(limiter, 'consume_in', outage)
                    response = await command(p, 'sell', {'item': 'wheat', 'qty': 1}, key='quota-outage')
                    assert response.status_code == 503 and response.json()['code'] == 'rate_unavailable'
                    assert response.headers['cache-control'] == 'no-store'
            assert await raw_farm(env, p) == before
            assert not await receipts(env, p.account_id, 'quota-outage')
            assert len((await buckets(env, 'account_write'))[0]['timestamps']) == 1
            assert len((await buckets(env, 'ip_write'))[0]['timestamps']) == 3
    asyncio.run(run())


def test_shared_farm_api_has_one_ingress_budget_and_flag_off_retains_local_fallback(farm_pg_url, shared, monkeypatch):
    async def run():
        async with environment(farm_pg_url) as env:
            # Cross the old host 120/IP threshold. Shared Farm's read budget is 600.
            for _ in range(125):
                assert (await env.client.get(API + '/config')).status_code == 200
            assert len((await buckets(env, 'ip_read'))[0]['timestamps']) == 125
            with monkeypatch.context() as patch:
                patch.delenv('QW_FARM_SHARED_RATE_ENABLED')
                patch.delenv('QW_FARM_RATE_SECRET')
                local = another_app(env)
            assert getattr(local.state, 'farm_shared_rate', None) is None
            async with peer(env, app=local) as client:
                for _ in range(600):   # farm reads join the frequent-read bucket (600 per client per minute)
                    assert (await client.get(API + '/config')).status_code == 200
                assert (await client.get(API + '/config')).status_code == 429
            assert len((await buckets(env, 'ip_read'))[0]['timestamps']) == 125
    asyncio.run(run())


def test_reauthenticate_after_quota_and_never_nest_pool_checkout(farm_pg_url, shared, monkeypatch):
    async def run():
        async with environment(farm_pg_url) as env, player(env) as p:
            limiter = env.app.state.farm_shared_rate
            original_consume = limiter.consume_in
            original_tx = env.db.transaction
            depth = ContextVar('quota_transaction_depth', default=0)
            counts = []
            @asynccontextmanager
            async def tracked():
                assert depth.get() == 0, 'nested checkout would exhaust a one-connection pool'
                token = depth.set(1)
                counts.append(1)
                try:
                    async with original_tx() as session:
                        yield session
                finally:
                    depth.reset(token)
            async def revoke_in_gap(session, scope, value):
                await original_consume(session, scope, value)
                if scope == 'account_write':
                    # Same committed preflight; game must independently recheck moderation.
                    from uuid import UUID
                    (await session.get(Account, UUID(p.account_id))).bot_blocked = True
            with monkeypatch.context() as patch:
                patch.setattr(env.db, 'transaction', tracked)
                patch.setattr(limiter, 'consume_in', revoke_in_gap)
                response = await command(p, 'sell', {'item': 'wheat', 'qty': 1}, key='quota-revoked')
                assert response.status_code == 401
            assert len(counts) == 3  # committed IP, committed account, rejected game authentication
            assert not await receipts(env, p.account_id, 'quota-revoked')
            assert len((await buckets(env, 'account_write'))[0]['timestamps']) == 2
    asyncio.run(run())


def test_single_connection_pool_completes_preflights_and_game(farm_pg_url, shared):
    async def run():
        async with environment(farm_pg_url) as env, player(env) as p:
            db = Database(DatabaseSettings(url=farm_pg_url, pool_size=1, max_overflow=0, pool_timeout=0.25))
            db.engine = db.engine.execution_options(**env.db.engine.get_execution_options())
            db.session_factory = async_sessionmaker(db.engine, expire_on_commit=False, autoflush=False)
            try:
                app = create_app(database=db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True),
                                 clock=lambda: env.now[0])
                async with peer(env, app=app, cookie=p.client.cookies.get('mqb_guest')) as client:
                    assert (await client.get(API + '/me?identity=guest')).status_code == 200
                    response = await client.post(API + '/commands?identity=guest', headers=FARM_HEADERS,
                        json={'command_id': 'quota-single-pool', 'actor': p.farm_id, 'kind': 'sell',
                              'target': p.farm_id, 'data': {'item': 'wheat', 'qty': 1}})
                    assert response.status_code == 200, response.text
                assert len(await receipts(env, p.account_id, 'quota-single-pool')) == 1
            finally:
                await db.dispose()
    asyncio.run(run())
