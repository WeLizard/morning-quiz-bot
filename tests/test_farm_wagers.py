"""PostgreSQL integration tests for Dasha wager persistence and idempotency."""
import asyncio
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from qw_farm.domain import new_farm
from qw_farm.expansion import upgrade_state
from qw_farm.integration import register_models
from qw_farm.persistence import Unit
from qw_farm.service import FarmService, Principal
from qw_farm.catalog import LEVELS
from qw_farm.wagers import day_bounds
from storage.database import normalize_database_url
from storage.models import Account
from application.account_merge import AccountMergeService
from storage.mini_app import MiniAppError
from qw_farm.domain import FarmError
from tests.local_database import isolated_database


def test_sqlite_partial_active_index_allows_a_second_round_after_settlement():
    metadata = sa.MetaData()
    sa.Table('accounts', metadata, sa.Column('id', sa.Uuid, primary_key=True))
    # Use the actual persistence table factory with a minimal parent account schema.
    from qw_farm.persistence import tables
    schema = tables(metadata)
    engine = sa.create_engine('sqlite://')
    metadata.create_all(engine)
    account_id, farm_id = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(metadata.tables['accounts'].insert().values(id=account_id))
        connection.execute(schema['states'].insert().values(id=farm_id, account_id=account_id, name='T',
            coins=100, xp=0, revision=0, visibility='private', payload={}))
        values = dict(id=uuid4(), account_id=account_id, farm_id=farm_id, stake=10, payout=27,
            rules_version=1, created_at=1., expires_at=601., winning_cup=0, default_cup=1)
        connection.execute(schema['wagers'].insert().values(**values))
        try:
            with connection.begin_nested():
                connection.execute(schema['wagers'].insert().values(**{**values, 'id': uuid4()}))
        except IntegrityError:
            pass
        else:
            raise AssertionError('a second active round was accepted')
        connection.execute(schema['wagers'].update().where(schema['wagers'].c.id == values['id']).values(
            chosen_cup=0, settled_at=2., won=True))
        connection.execute(schema['wagers'].insert().values(**{**values, 'id': uuid4()}))
    engine.dispose()


@asynccontextmanager
async def environment(url):
    schema = register_models()
    async with isolated_database(url) as (db, _):
        yield SimpleNamespace(db=db, schema=schema)


async def seeded(env, now, *, coins=40, credit=0):
    account_id = uuid4()
    async with env.db.transaction() as session:
        account = Account(id=account_id, display_name='Игрок')
        session.add(account)
        await session.flush()
        farm = upgrade_state(new_farm(str(uuid4()), 'Игрок', now))
        from qw_farm.catalog import LEVELS
        farm['xp'] = LEVELS[2]
        farm['coins'] = coins
        farm['starter_credit'] = credit
        farm['revision'] += 1
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


def test_wager_projection_hides_active_secret_and_new_key_cannot_pay_twice(pg_url):
    async def scenario():
        async with environment(pg_url) as env:
            now = [1_800_000_000]
            account, farm_id = await seeded(env, now[0])
            async with env.db.transaction() as session:
                service = FarmService(Unit(session, env.schema), Principal(str(account), 'Игрок'), clock=lambda: now[0])
                opened = await service.view()
                wager = opened['farm']['wager']
                assert wager['active'] is None
                assert wager['rules']['payouts'] == {'10': 27, '20': 54, '50': 135}
                started = await service.command('wager-start-001', 'wager_start', {'stake': 10})
                rid = started['wager']['active']['id']
                assert set(started['wager']['active']) == {'id', 'stake', 'payout', 'expires_at', 'rules_version'}
                assert 'winning_cup' not in repr(started['wager']) and 'default_cup' not in repr(started['wager'])
                assert started['wager']['eligible'] is False and started['wager']['reason'] == 'active'
                row = (await session.execute(select(env.schema['wagers']).where(
                    env.schema['wagers'].c.id == UUID(rid)))).mappings().one()
                winning = row['winning_cup']
                result = await service.command('wager-choose-01', 'wager_choose', {'round_id': rid, 'cup': winning})
                balance = result['wager']['earned_balance']
                assert result['wager']['last_result']['won'] is True
                assert balance == 57
                same_key = await service.command('wager-choose-01', 'wager_choose', {'round_id': rid, 'cup': winning})
                assert same_key['wager']['earned_balance'] == balance
                assert 'winning_cup' not in repr((await service.u.receipt(account, 'wager-choose-01'))['result'])
                with pytest.raises(FarmError):
                    await service.command('wager-choose-02', 'wager_choose', {'round_id': rid, 'cup': winning})
                assert (await service.view())['farm']['wager']['earned_balance'] == balance
                count = await session.scalar(select(func.count()).select_from(env.schema['ledger']).where(
                    env.schema['ledger'].c.farm_id == UUID(farm_id),
                    env.schema['ledger'].c.kind == 'wager_settle'))
                assert count == 1
    run(scenario())


def test_expired_round_uses_persisted_default_once_and_quota_remains(pg_url):
    async def scenario():
        async with environment(pg_url) as env:
            now = [1_800_000_000]
            account, farm_id = await seeded(env, now[0], coins=300)
            async with env.db.transaction() as session:
                service = FarmService(Unit(session, env.schema), Principal(str(account), 'Игрок'), clock=lambda: now[0])
                started = await service.command('wager-start-002', 'wager_start', {'stake': 50})
                rid = UUID(started['wager']['active']['id'])
                row = (await session.execute(select(env.schema['wagers']).where(env.schema['wagers'].c.id == rid))).mappings().one()
                await session.execute(env.schema['wagers'].update().where(env.schema['wagers'].c.id == rid).values(
                    default_cup=row['winning_cup']))
                await session.execute(env.schema['states'].update().where(
                    env.schema['states'].c.id == UUID(farm_id)).values(coins=10**12))
                now[0] += 601
                expired = await service.view()
                assert expired['farm']['wager']['active'] is None
                assert expired['farm']['wager']['last_result']['chosen_cup'] == row['winning_cup']
                assert expired['farm']['wager']['pending_payout'] == 135
                assert expired['farm']['wager']['last_result']['pending_payout'] == 135
                await session.execute(env.schema['states'].update().where(
                    env.schema['states'].c.id == UUID(farm_id)).values(coins=10**12-135))
                await service.view()
                claimed = await service.view()
                assert claimed['farm']['wager']['pending_payout'] == 0
                assert claimed['farm']['wager']['earned_balance'] == 10**12
                ledger = env.schema['ledger']
                settle_count = await session.scalar(select(func.count()).select_from(ledger).where(
                    ledger.c.farm_id == UUID(farm_id), ledger.c.kind == 'wager_settle'))
                claim_count = await session.scalar(select(func.count()).select_from(ledger).where(
                    ledger.c.farm_id == UUID(farm_id), ledger.c.kind == 'wager_claim'))
                assert settle_count == claim_count == 1
    run(scenario())


def test_wager_start_reserves_enough_wallet_headroom_for_the_full_payout(pg_url):
    async def scenario():
        async with environment(pg_url) as env:
            now = 1_800_000_000
            account, _ = await seeded(env, now, coins=10**12)
            async with env.db.transaction() as session:
                service = FarmService(Unit(session, env.schema), Principal(str(account), 'Игрок'), clock=lambda: now)
                with pytest.raises(FarmError) as error:
                    await service.command('wager-cap-001', 'wager_start', {'stake': 50})
                assert error.value.code == 'wager_balance_limit'
    run(scenario())


def test_starter_credit_only_balance_is_not_reported_as_eligible(pg_url):
    async def scenario():
        async with environment(pg_url) as env:
            now = 1_800_000_000
            account, _ = await seeded(env, now, coins=250, credit=250)
            async with env.db.transaction() as session:
                service = FarmService(Unit(session, env.schema), Principal(str(account), 'Игрок'), clock=lambda: now)
                wager = (await service.view())['farm']['wager']
                assert wager['earned_balance'] == 0
                assert wager['eligible'] is False and wager['reason'] == 'earned_balance'
    run(scenario())


def test_starter_credit_is_preserved_bad_types_are_rejected_and_daily_limit_is_atomic(pg_url):
    async def scenario():
        async with environment(pg_url) as env:
            now = [1_800_000_000]
            account, farm_id = await seeded(env, now[0], coins=400, credit=200)
            async with env.db.transaction() as session:
                service = FarmService(Unit(session, env.schema), Principal(str(account), 'Игрок'), clock=lambda: now[0])
                with pytest.raises(FarmError) as error:
                    await service.command('wager-bad-bool', 'wager_start', {'stake': True})
                assert error.value.code == 'invalid_command'
                started = await service.command('wager-earned-1', 'wager_start', {'stake': 50})
                rid = started['wager']['active']['id']
                with pytest.raises(FarmError) as error:
                    await service.command('wager-cup-float', 'wager_choose', {'round_id': rid, 'cup': 1.0})
                assert error.value.code == 'invalid_command'
                with pytest.raises(FarmError) as error:
                    await service.command('wager-cup-bool', 'wager_choose', {'round_id': rid, 'cup': True})
                assert error.value.code == 'invalid_command'
                row = (await session.execute(select(env.schema['wagers']).where(
                    env.schema['wagers'].c.id == UUID(rid)))).mappings().one()
                await service.command('wager-earned-2', 'wager_choose', {'round_id': rid,
                    'cup': (row['winning_cup']+1) % 3})
                farm = await service.u.by_account(account)
                assert farm['starter_credit'] == 200 and farm['xp'] == LEVELS[2] and farm['coins'] == 350
                for index in range(3):
                    started = await service.command(f'wager-quota-{index:02}', 'wager_start', {'stake': 50})
                    rid = UUID(started['wager']['active']['id'])
                    row = (await session.execute(select(env.schema['wagers']).where(
                        env.schema['wagers'].c.id == rid))).mappings().one()
                    await service.command(f'wager-quota-c{index:02}', 'wager_choose', {'round_id': str(rid),
                        'cup': (row['winning_cup']+1) % 3})
                status = await service.view()
                assert status['farm']['wager']['daily_staked'] == 200
                assert status['farm']['wager']['remaining_stake'] == 0
                with pytest.raises(FarmError) as error:
                    await service.command('wager-quota-over', 'wager_start', {'stake': 10})
                assert error.value.code == 'wager_daily_limit'
    run(scenario())


def test_two_tabs_cannot_create_two_rounds_or_settle_one_round_twice(pg_url):
    async def scenario():
        async with environment(pg_url) as env:
            now = 1_800_000_000
            account, farm_id = await seeded(env, now, coins=200)

            async def issue(key, kind, data):
                try:
                    async with env.db.transaction() as session:
                        service = FarmService(Unit(session, env.schema), Principal(str(account), 'Игрок'), clock=lambda: now)
                        return await service.command(key, kind, data)
                except FarmError as error:
                    return error

            starts = await asyncio.gather(
                issue('wager-race-start-1', 'wager_start', {'stake': 10}),
                issue('wager-race-start-2', 'wager_start', {'stake': 10}))
            created = [result for result in starts if isinstance(result, dict)]
            rejected = [result for result in starts if isinstance(result, FarmError)]
            assert len(created) == len(rejected) == 1 and rejected[0].code == 'wager_active'
            rid = created[0]['wager']['active']['id']
            async with env.db.transaction() as session:
                await session.execute(env.schema['wagers'].update().where(
                    env.schema['wagers'].c.id == UUID(rid)).values(winning_cup=2))
            choices = await asyncio.gather(
                issue('wager-race-choose-1', 'wager_choose', {'round_id': rid, 'cup': 2}),
                issue('wager-race-choose-2', 'wager_choose', {'round_id': rid, 'cup': 2}))
            settled = [result for result in choices if isinstance(result, dict)]
            rejected = [result for result in choices if isinstance(result, FarmError)]
            assert len(settled) == len(rejected) == 1
            async with env.db.transaction() as session:
                farm = await Unit(session, env.schema).by_account(account)
                assert farm['coins'] == 217
                for kind in ('wager_start', 'wager_settle'):
                    count = await session.scalar(select(func.count()).select_from(env.schema['ledger']).where(
                        env.schema['ledger'].c.farm_id == UUID(farm_id), env.schema['ledger'].c.kind == kind))
                    assert count == 1
    run(scenario())


def test_foreign_round_ids_and_non_owner_targets_never_disclose_a_round(pg_url):
    async def scenario():
        async with environment(pg_url) as env:
            now = 1_800_000_000
            owner, _ = await seeded(env, now, coins=100)
            guest, guest_farm = await seeded(env, now, coins=100)
            async with env.db.transaction() as session:
                service = FarmService(Unit(session, env.schema), Principal(str(guest), 'Друг'), clock=lambda: now)
                foreign = await service.command('wager-foreign-start', 'wager_start', {'stake': 10})
            async with env.db.transaction() as session:
                service = FarmService(Unit(session, env.schema), Principal(str(owner), 'Игрок'), clock=lambda: now)
                with pytest.raises(FarmError) as error:
                    await service.command('wager-foreign-id', 'wager_choose', {
                        'round_id': foreign['wager']['active']['id'], 'cup': 0})
                assert error.value.code == 'wager_not_found' and error.value.status == 404
                with pytest.raises(FarmError) as error:
                    await service.command('wager-malformed-uuid', 'wager_choose', {'round_id': 'not-a-uuid', 'cup': 0})
                assert error.value.code == 'invalid_command' and error.value.status == 422
                with pytest.raises(FarmError) as error:
                    await service.command('wager-non-owner-target', 'wager_start', {'stake': 10}, guest_farm)
                assert error.value.code == 'not_owner' and error.value.status == 403
    run(scenario())


def test_expiry_600_boundary_and_moscow_daily_quota_reset(pg_url):
    async def scenario():
        async with environment(pg_url) as env:
            now = [1_800_000_000]
            account, _ = await seeded(env, now[0], coins=1_000)
            async with env.db.transaction() as session:
                service = FarmService(Unit(session, env.schema), Principal(str(account), 'Игрок'), clock=lambda: now[0])
                first = await service.command('wager-boundary-1', 'wager_start', {'stake': 10})
                first_id = UUID(first['wager']['active']['id'])
                await session.execute(env.schema['wagers'].update().where(
                    env.schema['wagers'].c.id == first_id).values(default_cup=2, winning_cup=2))
                now[0] += 599
                assert (await service.view())['farm']['wager']['active']['id'] == str(first_id)
                # A choice at 599 seconds is honored.
                await service.command('wager-boundary-choose', 'wager_choose', {'round_id': str(first_id), 'cup': 1})
                second = await service.command('wager-boundary-2', 'wager_start', {'stake': 10})
                second_id = UUID(second['wager']['active']['id'])
                second_row = (await session.execute(select(env.schema['wagers']).where(
                    env.schema['wagers'].c.id == second_id))).mappings().one()
                await session.execute(env.schema['wagers'].update().where(
                    env.schema['wagers'].c.id == second_id).values(default_cup=1, winning_cup=1))
                now[0] = second_row['expires_at']
                expired = await service.view()
                assert expired['farm']['wager']['active'] is None
                assert expired['farm']['wager']['last_result']['id'] == str(second_id)
                assert expired['farm']['wager']['last_result']['chosen_cup'] == 1

            # Spend the full quota in the final second of a Moscow day, then start anew exactly at midnight.
            quota_now = [1_800_000_000]
            quota_account, _ = await seeded(env, quota_now[0], coins=500)
            _, day_end = day_bounds(quota_now[0])
            quota_now[0] = day_end-1
            async with env.db.transaction() as session:
                service = FarmService(Unit(session, env.schema), Principal(str(quota_account), 'Квота'),
                                     clock=lambda: quota_now[0])
                for i in range(4):
                    started = await service.command(f'wager-midnight-{i}', 'wager_start', {'stake': 50})
                    rid = UUID(started['wager']['active']['id'])
                    row = (await session.execute(select(env.schema['wagers']).where(
                        env.schema['wagers'].c.id == rid))).mappings().one()
                    await service.command(f'wager-midnight-c{i}', 'wager_choose', {
                        'round_id': str(rid), 'cup': (row['winning_cup']+1) % 3})
                assert (await service.view())['farm']['wager']['remaining_stake'] == 0
                quota_now[0] = day_end
                midnight = await service.view()
                assert midnight['farm']['wager']['daily_staked'] == 0
                assert midnight['farm']['wager']['remaining_stake'] == 200
                await service.command('wager-midnight-newday', 'wager_start', {'stake': 10})
    run(scenario())


def test_rollback_after_wager_debit_removes_round_receipt_and_ledger_then_retry_works(pg_url, monkeypatch):
    async def scenario():
        async with environment(pg_url) as env:
            now = 1_800_000_000
            account, farm_id = await seeded(env, now, coins=100)
            original = Unit.record

            async def fail_wager_record(unit, actor, key, kind, before, after, at):
                if kind == 'wager_start':
                    raise RuntimeError('injected ledger failure')
                return await original(unit, actor, key, kind, before, after, at)

            monkeypatch.setattr(Unit, 'record', fail_wager_record)
            with pytest.raises(RuntimeError, match='injected ledger failure'):
                async with env.db.transaction() as session:
                    service = FarmService(Unit(session, env.schema), Principal(str(account), 'Игрок'), clock=lambda: now)
                    await service.command('wager-rollback-1', 'wager_start', {'stake': 10})
            async with env.db.transaction() as session:
                unit = Unit(session, env.schema)
                farm = await unit.by_account(account)
                assert farm['coins'] == 100
                for table in (env.schema['wagers'], env.schema['receipts'], env.schema['ledger']):
                    count = await session.scalar(select(func.count()).select_from(table).where(
                        table.c.account_id == account if table is env.schema['receipts'] else
                        table.c.farm_id == UUID(farm_id) if table is not env.schema['wagers'] else
                        table.c.account_id == account))
                    assert count == 0
            monkeypatch.setattr(Unit, 'record', original)
            async with env.db.transaction() as session:
                service = FarmService(Unit(session, env.schema), Principal(str(account), 'Игрок'), clock=lambda: now)
                result = await service.command('wager-rollback-1', 'wager_start', {'stake': 10})
                assert result['wager']['active']['stake'] == 10
                assert (await service.u.by_account(account))['coins'] == 90
    run(scenario())


def test_merge_rejects_active_wager_and_moves_settled_history_with_both_farms(pg_url):
    async def scenario():
        async with environment(pg_url) as env:
            now = 1_800_000_000
            main, _ = await seeded(env, now, coins=300)
            secondary, secondary_farm = await seeded(env, now, coins=300)
            t = env.schema['wagers']
            ledger = env.schema['ledger']
            async with env.db.transaction() as session:
                await Unit(session, env.schema).execute(t.insert().values(id=uuid4(), account_id=secondary,
                    farm_id=UUID(secondary_farm), stake=10, payout=27, rules_version=1,
                    created_at=now, expires_at=now+600, winning_cup=0, default_cup=1))
            with pytest.raises(MiniAppError) as error:
                async with env.db.transaction() as session:
                    await AccountMergeService().merge_in(session, main=await session.get(Account, main),
                        secondary=await session.get(Account, secondary), via='test')
            assert error.value.code == 'merge_wager_unsettled'
            async with env.db.transaction() as session:
                await session.execute(t.update().where(t.c.account_id == secondary).values(
                    chosen_cup=0, settled_at=now+1, won=True))
                await session.execute(ledger.insert().values(id=uuid4(), farm_id=UUID(secondary_farm),
                    actor_account_id=secondary, command_id='historic-wager', kind='wager_settle',
                    coins_delta=17, coins_after=317, inventory_delta={}, xp_delta=0, created_at=now+1))
            async with env.db.transaction() as session:
                await AccountMergeService().merge_in(session, main=await session.get(Account, main),
                    secondary=await session.get(Account, secondary), via='test')
            async with env.db.transaction() as session:
                wager = (await session.execute(select(t).where(t.c.account_id == main))).mappings().one()
                moved_ledger = (await session.execute(select(ledger).where(
                    ledger.c.command_id == 'historic-wager'))).mappings().one()
                assert str(wager['farm_id']) == secondary_farm
                assert str(moved_ledger['farm_id']) == secondary_farm
                assert str(moved_ledger['actor_account_id']) == str(secondary)
    run(scenario())
