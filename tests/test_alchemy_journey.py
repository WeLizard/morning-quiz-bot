"""Verified expeditions and replay boundaries in private disposable PG schemas."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
import json
import time
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, inspect, select, text

from domain.alchemy_journey import catalog_revision, validate_stage
from storage.alchemy import AlchemyService, BASE_ELEMENTS, load_catalog
from storage.guest_accounts import GuestAccounts
from storage.mini_app import MiniAppError
from storage.models import (Account, AchievementGrant, AlchemyClaimCommand,
    AlchemyCraftCommand, AlchemyProgress, AlchemyStageClaim, User)
from tests.local_database import isolated_database
from tests.test_postgres_members import pg_env
from tests.test_mini_app import ORIGIN, TOKEN, signed
from web.mini_app import MiniAppSettings, create_app

CATALOG = load_catalog()
REVISION = CATALOG.revision


def chain(goals):
    opened, used, result = set(BASE_ELEMENTS), set(), []
    while not set(goals) <= opened:
        candidates = [(key, recipe) for key, recipe in CATALOG.recipes.items()
                      if key not in used and {recipe[0], recipe[1]} <= opened]
        assert candidates, 'Catalog goals must be reachable'
        for key, recipe in candidates:
            used.add(key)
            if recipe[2] not in opened:
                opened.add(recipe[2])
                result.append(recipe)
    return result


async def guest(db):
    profile, raw = await GuestAccounts(db).start()
    return AlchemyService(db), raw, profile['account_id']


async def craft_goals(service, raw, account_id, goals):
    for index, recipe in enumerate(chain(goals)):
        response = await service.guest_craft(raw, expected_account_id=account_id,
            command_id=f'chain-{index:04d}', ingredient_a=recipe[0], ingredient_b=recipe[1])
        assert response['verified'] is True and response['awarded'] == 0


def test_domain_requires_verified_result_and_previous_stages():
    stage = CATALOG.stages['garden1']
    with pytest.raises(ValueError, match='Открытия'):
        validate_stage(stage, claimed=[], verified_discovered=[],
            verified_crafted=CATALOG.recipe_keys, recipes=CATALOG.recipes)
    with pytest.raises(ValueError, match='Эксперимент'):
        validate_stage(stage, claimed=[], verified_discovered=stage.goals,
            verified_crafted=[], recipes=CATALOG.recipes)
    with pytest.raises(ValueError, match='предыдущие'):
        validate_stage(CATALOG.stages['garden2'], claimed=[],
            verified_discovered=CATALOG.element_ids,
            verified_crafted=CATALOG.recipe_keys, recipes=CATALOG.recipes)
    raw = {'x': [1, 2], 'y': 3}
    assert catalog_revision(raw) == catalog_revision({'y': 3, 'x': [1, 2]})
    assert catalog_revision(raw) != catalog_revision({'x': [1, 3], 'y': 3})


def test_guest_false_pair_reverifies_only_after_legitimate_chain(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            service, raw, account_id = await guest(db)
            first = await service.guest_craft(raw, expected_account_id=account_id,
                command_id='unverified-pair-01', ingredient_a='air', ingredient_b='steam')
            assert first['verified'] is False
            await service.guest_craft(raw, expected_account_id=account_id,
                command_id='verify-steam-0001', ingredient_a='fire', ingredient_b='water')
            # Reproduce the previous DB invariant in this test's private schema:
            # it blocks the same pair even after its prerequisites are verified.
            async with db.engine.begin() as connection:
                await connection.exec_driver_sql('ALTER TABLE alchemy_craft_commands ADD CONSTRAINT uq_alchemy_craft_account_recipe UNIQUE (account_id, ingredient_a, ingredient_b)')
            with pytest.raises(MiniAppError) as old_constraint:
                await service.guest_craft(raw, expected_account_id=account_id,
                    command_id='verified-pair-0002', ingredient_a='steam', ingredient_b='air')
            assert old_constraint.value.status == 409
            async with db.engine.begin() as connection:
                await connection.exec_driver_sql('ALTER TABLE alchemy_craft_commands DROP CONSTRAINT uq_alchemy_craft_account_recipe')
            second = await service.guest_craft(raw, expected_account_id=account_id,
                command_id='verified-pair-0002', ingredient_a='steam', ingredient_b='air')
            assert second['verified'] is True and second['result'] == first['result']
            assert (await service.guest_craft(raw, expected_account_id=account_id,
                command_id='unverified-pair-01', ingredient_a='air', ingredient_b='steam')) == first
            with pytest.raises(MiniAppError) as error:
                await service.guest_craft(raw, expected_account_id=account_id,
                    command_id='verified-pair-0002', ingredient_a='earth', ingredient_b='earth')
            assert error.value.status == 409
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(User)) == 0
                assert await session.scalar(select(func.count()).select_from(AchievementGrant)) == 0
                assert await session.scalar(select(func.count()).select_from(AlchemyCraftCommand)) == 3
                assert (await session.get(AlchemyProgress, UUID(account_id))).points_total == Decimal('0')
    asyncio.run(run())


def test_import_is_not_evidence_claim_replay_concurrency_snapshot_and_ownership(pg_env, monkeypatch):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            service, raw, account_id = await guest(db)
            await service.guest_sync(raw, expected_account_id=account_id,
                discovered=CATALOG.element_ids, crafted=CATALOG.recipe_keys, attempts=99999)
            command = {'command_id': 'claim-recovery-0001', 'stage_id': 'garden1',
                       'catalog_revision': REVISION}
            with pytest.raises(MiniAppError) as error:
                await service.guest_claim_stage(raw, expected_account_id=account_id, **command)
            assert error.value.code == 'stage_ineligible'
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(AlchemyClaimCommand)) == 0
            await craft_goals(service, raw, account_id, CATALOG.stages['garden1'].goals)
            responses = await asyncio.gather(*[service.guest_claim_stage(raw,
                expected_account_id=account_id, **{**command, 'command_id': f'claim-concurrent-{i:02d}'})
                for i in range(5)])
            assert sum(r['awarded_expedition_points'] for r in responses) == 10
            assert all(r['expedition_points'] == 10 for r in responses)
            replayed = await asyncio.gather(*[service.guest_claim_stage(raw,
                expected_account_id=account_id, **{**command, 'command_id': 'claim-concurrent-00'})
                for _ in range(3)])
            assert all(result == responses[0] for result in replayed)
            first = await service.guest_claim_stage(raw, expected_account_id=account_id, **command)
            assert first['awarded_expedition_points'] == 0
            with pytest.raises(MiniAppError) as reused:
                await service.guest_claim_stage(raw, expected_account_id=account_id,
                    **{**command, 'stage_id': 'garden2'})
            assert reused.value.code == 'command_reused'
            # Reward/receipt remains a snapshot even if a later catalog changes.
            with monkeypatch.context() as patch:
                from dataclasses import replace
                patch.setattr('application.alchemy_journey.load_catalog',
                              lambda: replace(CATALOG, revision='f' * 64))
                assert await service.guest_claim_stage(raw, expected_account_id=account_id, **command) == first
            restored = await AlchemyService(db).guest_progress(raw)
            assert restored['claims'] == ['garden1'] and restored['expedition_points'] == 10
            assert restored['crafted'] and restored['attempts'] == 99999
            assert restored['claim_receipts'][0]['reward'] == {'points': 10, 'seal': CATALOG.stages['garden1'].seal}
            _, other_raw, other_id = await guest(db)
            with pytest.raises(MiniAppError) as owner:
                await service.guest_claim_stage(other_raw, expected_account_id=other_id, **command)
            assert owner.value.code == 'command_reused'
            assert (await service.guest_progress(other_raw))['claims'] == []
            with pytest.raises(MiniAppError) as stale:
                await service.guest_claim_stage(raw, expected_account_id=account_id,
                    **{**command, 'command_id': 'stale-catalog-001', 'catalog_revision': '0' * 64})
            assert stale.value.code == 'catalog_changed'
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(AlchemyStageClaim)) == 1
                (await session.get(Account, UUID(account_id))).moderation_revision += 1
            with pytest.raises(MiniAppError) as blocked:
                await service.guest_claim_stage(raw, expected_account_id=account_id, **command)
            assert blocked.value.status == 401
    asyncio.run(run())


def test_mini_cookie_switch_cannot_write_or_project_into_original_actor(pg_env):
    async def run():
        now = int(time.time())
        async with isolated_database(pg_env) as (db, _):
            app = create_app(database=db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True), clock=lambda: now)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                for user_id in (981020000061, 981020000062):
                    response = await client.post('/api/mini/session', json={
                        'init_data': signed(user_id, date=now, query_id=f'actor-fence-{user_id}')})
                    assert response.status_code == 200
                    assert (await client.get('/api/mini/me')).json()['user_id'] == str(user_id)
                headers = {'Origin': ORIGIN, 'X-Mini-CSRF': '1', 'X-Mini-User': '981020000061'}
                cases = [('sync', {'discovered': ['steam']}),
                    ('craft', {'command_id': 'actor-fence-craft-01', 'ingredient_a': 'water', 'ingredient_b': 'fire'}),
                    ('claim-stage', {'command_id': 'actor-fence-claim-01', 'stage_id': 'garden1', 'catalog_revision': REVISION})]
                for route, payload in cases:
                    response = await client.post('/api/mini/alchemy/' + route, headers=headers, json=payload)
                    assert response.status_code == 409 and response.json()['code'] == 'profile_changed'
                projection = await client.get('/api/mini/alchemy', headers=headers)
                assert projection.status_code == 409 and projection.json()['code'] == 'profile_changed'
                async with db.transaction() as session:
                    for model in (AlchemyProgress, AlchemyCraftCommand, AlchemyStageClaim, AlchemyClaimCommand):
                        assert await session.scalar(select(func.count()).select_from(model)) == 0
                accepted = await client.post('/api/mini/alchemy/sync', headers={**headers, 'X-Mini-User': '981020000062'}, json={'discovered': ['steam']})
                assert accepted.status_code == 200
                assert (await client.post('/api/mini/alchemy/sync', headers={'Origin': ORIGIN, 'X-Mini-CSRF': '1'}, json={})).status_code == 422
    asyncio.run(run())


def test_guest_logout_and_expiry_reject_claim_without_receipt(pg_env):
    async def run():
        from storage.models import GuestSession
        from storage.guest_accounts import credential_hash
        async with isolated_database(pg_env) as (db, _):
            service, raw, account_id = await guest(db)
            command = {'expected_account_id': account_id, 'command_id': 'ended-session-claim',
                       'stage_id': 'garden1', 'catalog_revision': REVISION}
            await GuestAccounts(db).logout(raw)
            with pytest.raises(MiniAppError) as logout:
                await service.guest_claim_stage(raw, **command)
            assert logout.value.status == 401
            _, expired, expired_id = await guest(db)
            async with db.transaction() as session:
                (await session.get(GuestSession, credential_hash(expired))).expires_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
            with pytest.raises(MiniAppError) as expiry:
                await service.guest_claim_stage(expired, **{**command, 'expected_account_id': expired_id})
            assert expiry.value.status == 401
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(AlchemyClaimCommand)) == 0
                assert await session.scalar(select(func.count()).select_from(AlchemyStageClaim)) == 0
    asyncio.run(run())


def test_claim_failure_after_insert_rolls_back_claim_and_receipt(pg_env, monkeypatch):
    async def run():
        import application.alchemy_journey as journey
        async with isolated_database(pg_env) as (db, _):
            service, raw, account_id = await guest(db)
            await craft_goals(service, raw, account_id, CATALOG.stages['garden1'].goals)
            original, calls = journey.journey_projection, []
            async def fail_after_claim(session, actor):
                calls.append(actor)
                if len(calls) == 2:
                    raise RuntimeError('synthetic projection failure')
                return await original(session, actor)
            with monkeypatch.context() as patch:
                patch.setattr(journey, 'journey_projection', fail_after_claim)
                with pytest.raises(RuntimeError, match='synthetic'):
                    await service.guest_claim_stage(raw, expected_account_id=account_id,
                        command_id='rollback-claim-01', stage_id='garden1', catalog_revision=REVISION)
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(AlchemyStageClaim)) == 0
                assert await session.scalar(select(func.count()).select_from(AlchemyClaimCommand)) == 0
            assert (await service.guest_claim_stage(raw, expected_account_id=account_id,
                command_id='rollback-claim-01', stage_id='garden1', catalog_revision=REVISION))['awarded_expedition_points'] == 10
    asyncio.run(run())


@pytest.mark.parametrize('identity', ['guest', 'mini'])
def test_http_strict_auth_claim_and_restore(pg_env, identity):
    async def run():
        now = int(time.time())
        async with isolated_database(pg_env) as (db, _):
            app = create_app(database=db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True), clock=lambda: now)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                prefix = '/api/' + identity + '/alchemy'
                headers = {'Origin': ORIGIN, 'X-Guest-CSRF' if identity == 'guest' else 'X-Mini-CSRF': '1'}
                if identity == 'guest':
                    profile = await client.post('/api/guest/start', headers=headers)
                    account_id = profile.json()['account_id']
                    headers['X-Guest-Account'] = account_id
                else:
                    response = await client.post('/api/mini/session', json={'init_data': signed(981020000029, date=now, query_id='alchemy-claim-test')})
                    assert response.status_code == 200, response.text
                    headers['X-Mini-User'] = '981020000029'
                    async with db.transaction() as session:
                        account_id = str((await session.get(User, 981020000029)).account_id)
                body = {'command_id': 'http-claim-0001', 'stage_id': 'garden1', 'catalog_revision': REVISION}
                assert (await client.post(prefix + '/claim-stage', json=body)).status_code == 403
                for invalid in ({**body, 'claims': ['garden1']}, {**body, 'stage_id': None}):
                    assert (await client.post(prefix + '/claim-stage', headers=headers, json=invalid)).status_code == 400
                duplicate = '{"command_id":"http-claim-0001","command_id":"http-claim-0002","stage_id":"garden1","catalog_revision":"' + REVISION + '"}'
                assert (await client.post(prefix + '/claim-stage', headers={**headers, 'Content-Type': 'application/json'}, content=duplicate)).status_code == 400
                assert (await client.post(prefix + '/claim-stage', headers=headers, content='x' * 513)).status_code == 415
                assert (await client.post(prefix + '/claim-stage', headers={**headers, 'Content-Type': 'application/json'}, content='x' * 513)).status_code == 413
                imported = await client.post(prefix + '/sync', headers=headers,
                    json={'discovered': sorted(CATALOG.element_ids), 'crafted': sorted(CATALOG.recipe_keys), 'attempts': 1000})
                assert imported.status_code == 200 and imported.json()['claims'] == []
                rejected = await client.post(prefix + '/claim-stage', headers=headers, json=body)
                assert rejected.status_code == 409 and rejected.json()['code'] == 'stage_ineligible'
                for index, recipe in enumerate(chain(CATALOG.stages['garden1'].goals)):
                    crafted = await client.post(prefix + '/craft', headers=headers, json={
                        'command_id': f'http-chain-{index:04d}', 'ingredient_a': recipe[0], 'ingredient_b': recipe[1]})
                    assert crafted.status_code == 200 and crafted.json()['verified'] is True, crafted.text
                async with db.transaction() as session:
                    score_before = (await session.get(User, 981020000029)).global_score if identity == 'mini' else 0
                claimed = await client.post(prefix + '/claim-stage', headers=headers, json=body)
                assert claimed.status_code == 200 and claimed.json()['expedition_points'] == 10
                assert (await client.post(prefix + '/claim-stage', headers=headers, json=body)).json() == claimed.json()
                restored = (await client.post(prefix + '/sync', headers=headers, json={})).json()
                assert restored['crafted'] and restored['attempts'] == 1000 and restored['claims'] == ['garden1']
                assert set(CATALOG.stages['garden1'].goals) <= set(restored['verified_discovered'])
                async with db.transaction() as session:
                    assert await session.scalar(select(func.count()).select_from(AlchemyStageClaim)) == 1
                    if identity == 'mini':
                        assert (await session.get(User, 981020000029)).global_score == score_before
                    else:
                        assert await session.scalar(select(func.count()).select_from(User)) == 0
                if identity == 'guest':
                    changed = await client.post(prefix + '/craft', headers={**headers, 'X-Guest-Account': '00000000-0000-0000-0000-000000000000'},
                        json={'command_id': 'stale-tab-00001', 'ingredient_a': 'water', 'ingredient_b': 'fire'})
                    assert changed.status_code == 409 and changed.json()['code'] == 'profile_changed'
    asyncio.run(run())


def test_additive_migration_preserves_progress_and_blocks_receipt_loss(pg_env, monkeypatch):
    async def run():
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from alembic.script import ScriptDirectory
        migration = ScriptDirectory.from_config(Config('alembic.ini')).get_revision('20261009_0025').module
        async with isolated_database(pg_env) as (db, _):
            service, raw, account_id = await guest(db)
            await service.guest_sync(raw, expected_account_id=account_id, discovered=['steam'], attempts=10)
            async with db.engine.begin() as connection:
                def roundtrip(sync):
                    before = list(sync.execute(text('SELECT * FROM alchemy_progress')).mappings())
                    operations = Operations(MigrationContext.configure(sync))
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', operations)
                        migration.downgrade()
                        assert 'uq_alchemy_craft_account_recipe' in {c['name'] for c in inspect(sync).get_unique_constraints('alchemy_craft_commands')}
                        migration.upgrade()
                    assert list(sync.execute(text('SELECT * FROM alchemy_progress')).mappings()) == before
                    assert not inspect(sync).get_unique_constraints('alchemy_craft_commands')
                await connection.run_sync(roundtrip)
            await craft_goals(service, raw, account_id, CATALOG.stages['garden1'].goals)
            await service.guest_claim_stage(raw, expected_account_id=account_id,
                command_id='migration-claim-01', stage_id='garden1', catalog_revision=REVISION)
            async with db.engine.begin() as connection:
                def blocked(sync):
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', Operations(MigrationContext.configure(sync)))
                        with pytest.raises(RuntimeError, match='Preserve expedition'):
                            migration.downgrade()
                    assert sync.scalar(text('SELECT count(*) FROM alchemy_stage_claims')) == 1
                await connection.run_sync(blocked)
    asyncio.run(run())


def test_complete_alembic_chain_reaches_new_head_in_private_schema(pg_env):
    async def run():
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from alembic.runtime.environment import EnvironmentContext
        from alembic.script import ScriptDirectory
        from storage.models import Base
        from qw_farm.integration import register_models
        register_models()
        scripts = ScriptDirectory.from_config(Config('alembic.ini'))
        assert scripts.get_heads() == ['20261016_0036']
        async with isolated_database(pg_env) as (db, schema):
            async with db.engine.begin() as connection:
                # Remove only this fixture's empty synthetic tables to exercise
                # real Alembic from base instead of create_all.
                await connection.run_sync(Base.metadata.drop_all)
                def upgrade(sync):
                    with EnvironmentContext(Config('alembic.ini'), scripts,
                            fn=lambda current, _: scripts._upgrade_revs('head', current)) as environment:
                        environment.configure(connection=sync, version_table_schema=schema)
                        environment.run_migrations()
                    assert sync.scalar(text('SELECT version_num FROM alembic_version')) == '20261016_0036'
                    tables = set(inspect(sync).get_table_names())
                    assert {'alchemy_progress', 'alchemy_craft_commands', 'alchemy_stage_claims', 'alchemy_claim_commands'} <= tables
                    for name in ('alchemy_stage_claims', 'alchemy_claim_commands'):
                        assert {column['name'] for column in inspect(sync).get_columns(name)} == set(Base.metadata.tables[name].columns.keys())
                    assert not inspect(sync).get_unique_constraints('alchemy_craft_commands')
                await connection.run_sync(upgrade)
    asyncio.run(run())


def test_existing_mini_login_and_craft_contract_in_private_schemas(pg_env, monkeypatch):
    from tests import test_mini_app as existing
    @asynccontextmanager
    async def private_scenario(url):
        async with isolated_database(url) as (database, _):
            yield database
    monkeypatch.setattr(existing, 'scenario', private_scenario)
    existing.test_login_uses_http_only_cookie_and_cookie_writes_require_csrf(pg_env)
    existing.test_alchemy_sync_imports_without_reward_and_craft_is_server_authoritative(pg_env)
