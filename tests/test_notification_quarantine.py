"""Offline orphan quarantine acceptance in private real PostgreSQL schemas."""
import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from scripts import quarantine_notification_outbox as cli
from storage.models import (NotificationOutbox, NotificationQuarantineReceipt, NotificationResolution,
                            Game, GameDelivery, Room, User)
from storage.notifications import NotificationQueue, NotificationResolutionConflict, SENDERS_STOPPED_ATTESTATION
from tests.local_database import isolated_database
from tests.test_postgres_members import pg_env


async def sending_request(database, key='one'):
    async with database.transaction() as session:
        await NotificationQueue.enqueue_in(session, kind='quarantine-test', dedupe_key=key,
                                           chat_id=-100, payload={'secret': 'never-export'})
    queue = NotificationQueue(database)
    item = await queue.claim('same-worker')
    async with database.transaction() as session:
        row = await session.get(NotificationOutbox, item['id'])
        return dict(item_id=row.id, action_id=str(uuid4()), operator_id='operator:a',
                    expected_version=row.version, expected_claimed_by=row.claimed_by,
                    expected_claimed_at=row.claimed_at, reason='Orphan process stopped',
                    evidence={'verification_method': 'Independent process and transport review',
                              'sender_inventory': 'All synthetic deployments stopped; no in-flight HTTP'},
                    senders_stopped_attestation=SENDERS_STOPPED_ATTESTATION)


def test_quarantine_replay_callbacks_terminal_resolution_and_durable_receipt(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            args = await sending_request(database)
            queue = NotificationQueue(database)
            receipt = await queue.quarantine(**args)
            assert receipt['status'] == 'uncertain' and receipt['version'] == 2
            assert await queue.quarantine(**args) == receipt
            assert not await queue.delivered(args['item_id'], 'same-worker', claim_version=1)
            assert not await queue.retry_after(args['item_id'], 'same-worker', 0, claim_version=1)
            assert not await queue.uncertain(args['item_id'], 'same-worker', 'late', claim_version=1)
            assert await queue.claim('other', now=datetime.now(timezone.utc) + timedelta(days=90)) is None
            async with database.transaction() as session:
                row = await session.get(NotificationOutbox, args['item_id'])
                assert (row.status, row.version, row.attempts) == ('uncertain', 2, 1)
                assert row.payload == {'secret': 'never-export'} and row.chat_id == -100
                assert row.claimed_at == args['expected_claimed_at']
                assert row.claimed_by == args['expected_claimed_by']
                assert row.delivered_at is None and row.resolved_at is None
                assert row.last_error == 'OperatorQuarantine'
                assert await session.scalar(select(func.count()).select_from(NotificationResolution)) == 0
            resolution = dict(item_id=args['item_id'], action_id=str(uuid4()), operator_id='operator:a',
                              expected_version=2, decision='closed_without_resend', reason='Unverifiable',
                              evidence={'verification_method': 'manual review'})
            with pytest.raises(NotificationResolutionConflict, match='action_id'):
                await queue.resolve(**dict(resolution, action_id=args['action_id']))
            await queue.resolve(**resolution)
            assert await queue.quarantine(**args) == receipt  # Original result, not current state.
            with pytest.raises(NotificationResolutionConflict, match='action_id'):
                await queue.quarantine(**dict(args, action_id=resolution['action_id']))
            async with database.transaction() as session:
                await session.execute(delete(NotificationOutbox).where(NotificationOutbox.id == args['item_id']))
            assert await queue.quarantine(**args) == receipt
            assert 'never-export' not in str(receipt) and 'evidence' not in receipt
    asyncio.run(run())


def test_quarantine_concurrent_operators_replay_and_address_conflicts(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            args = await sending_request(database)
            queue = NotificationQueue(database)
            a, b = await asyncio.gather(queue.quarantine(**args), queue.quarantine(**args))
            assert a == b
            with pytest.raises(NotificationResolutionConflict, match='action_id'):
                await queue.quarantine(**dict(args, reason='Changed request'))
            second = await sending_request(database, key='two')
            with pytest.raises(NotificationResolutionConflict, match='action_id'):
                await queue.quarantine(**dict(second, action_id=args['action_id']))
            results = await asyncio.gather(queue.quarantine(**second),
                queue.quarantine(**dict(second, action_id=str(uuid4()), operator_id='operator:b')),
                return_exceptions=True)
            assert sum(isinstance(x, dict) for x in results) == 1
            assert sum(isinstance(x, NotificationResolutionConflict) for x in results) == 1
            async with database.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(NotificationQuarantineReceipt)) == 2
    asyncio.run(run())


def test_quarantine_does_not_change_game_score_or_classic_poll_binding(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            async with database.transaction() as session:
                session.add(Room(id='room', kind='standalone', title='Synthetic'))
                session.add(User(id=42, display_name='Synthetic', global_score=17, total_answered=3))
                await session.flush()
                session.add(Game(id='game', room_id='room', mode='classic', status='active',
                                 phase='question', revision=7, state={'poll_id': 'existing-poll'}))
                await session.flush()
                session.add(GameDelivery(id='binding', game_id='game', round_id='round', channel='telegram',
                                         kind='poll', external_id='existing-poll', chat_id=-100,
                                         message_id=42, status='delivered', metadata_json={'options': ['a', 'b']}))
            args = await sending_request(database)
            async with database.transaction() as session:
                (await session.get(NotificationOutbox, args['item_id'])).game_id = 'game'
            async def snapshot():
                async with database.transaction() as session:
                    return {model.__tablename__: list((await session.execute(select(model.__table__))).mappings())
                            for model in (Game, GameDelivery, Room, User)}
            before = await snapshot()
            await NotificationQueue(database).quarantine(**args)
            assert await snapshot() == before
    asyncio.run(run())


def test_quarantine_rejects_stale_claim_missing_stop_evidence_and_rolls_back(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            args = await sending_request(database)
            queue = NotificationQueue(database)
            for change in ({'expected_version': 0}, {'expected_claimed_by': 'another'},
                           {'expected_claimed_at': args['expected_claimed_at'] - timedelta(seconds=1)}):
                with pytest.raises(NotificationResolutionConflict):
                    await queue.quarantine(**dict(args, **change))
            for change in ({'senders_stopped_attestation': ''}, {'evidence': {}},
                           {'expected_claimed_at': datetime.now()}, {'action_id': 'invalid'},
                           {'reason': ' '}, {'expected_version': True}):
                with pytest.raises(ValueError):
                    await queue.quarantine(**dict(args, **change))
            with pytest.raises(RuntimeError, match='rollback'):
                async with database.transaction() as session:
                    await queue.quarantine_in(session, **args)
                    raise RuntimeError('rollback')
            async with database.transaction() as session:
                assert (await session.get(NotificationOutbox, args['item_id'])).status == 'sending'
                assert await session.get(NotificationQuarantineReceipt, args['action_id']) is None
            assert await queue.retry_after(args['item_id'], 'same-worker', 0, claim_version=1)
            new_claim = await queue.claim('same-worker')
            assert new_claim['claim_version'] == 3
            with pytest.raises(NotificationResolutionConflict):
                await queue.quarantine(**args)
            assert await queue.delivered(args['item_id'], 'same-worker', claim_version=3)
            with pytest.raises(NotificationResolutionConflict, match='sending'):
                await queue.quarantine(**dict(args, expected_version=4))
    asyncio.run(run())


def test_nullable_legacy_claim_and_loaded_state_refresh(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            args = await sending_request(database)
            queue = NotificationQueue(database)
            async with database.transaction() as session:
                row = await session.get(NotificationOutbox, args['item_id'])
                row.claimed_by = None
                row.claimed_at = None
            args.update(expected_claimed_by=None, expected_claimed_at=None)
            async with database.transaction() as session:
                observed = await session.get(NotificationOutbox, args['item_id'])
                await queue.quarantine(**args)
                with pytest.raises(NotificationResolutionConflict):
                    await queue.quarantine_in(session, **dict(args, action_id=str(uuid4())))
                assert observed.status == 'uncertain' and observed.version == 2
    asyncio.run(run())


def test_cli_dry_run_rolls_back_and_apply_uses_same_locked_contract(pg_env, monkeypatch):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            args = await sending_request(database)
            async def no_dispose():
                pass
            monkeypatch.setattr(cli, 'Database', lambda settings: SimpleNamespace(
                session_factory=database.session_factory, dispose=no_dispose))
            result = await cli.run(pg_env, args)
            assert result['applied'] is False
            async with database.transaction() as session:
                assert (await session.get(NotificationOutbox, args['item_id'])).status == 'sending'
                assert await session.get(NotificationQuarantineReceipt, args['action_id']) is None
            applied = await cli.run(pg_env, args, apply=True)
            assert applied['applied'] is True
            assert (await cli.run(pg_env, args, apply=True))['receipt'] == applied['receipt']
    asyncio.run(run())


def test_cli_target_guard_no_environment_default_or_credential_output(monkeypatch, capsys):
    for url in (None, '', 'postgresql://mqb_dev:SECRET@remote:5432/morning_quiz_dev',
                'postgresql://mqb_dev:SECRET@127.0.0.1:55433/production',
                'postgresql://mqb_dev:SECRET@127.0.0.1:55433/morning_quiz_dev?host=remote'):
        with pytest.raises(ValueError):
            cli.validate_dev_database_url(url)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://SECRET@production/database')
    with pytest.raises(SystemExit):
        cli.main([])
    assert 'SECRET' not in capsys.readouterr().err


def test_additive_quarantine_migration_preserves_existing_outbox(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            args = await sending_request(database)
            path = Path(__file__).resolve().parents[1] / 'alembic/versions/20261009_0023_notification_quarantine.py'
            spec = importlib.util.spec_from_file_location('quarantine_migration', path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            assert migration.down_revision == '20261009_0022'
            async with database.engine.begin() as connection:
                await connection.exec_driver_sql('DROP TABLE notification_quarantine_receipts')
                def apply(sync_connection):
                    from alembic.migration import MigrationContext
                    from alembic.operations import Operations
                    with Operations.context(MigrationContext.configure(sync_connection)):
                        migration.upgrade()
                await connection.run_sync(apply)
            async with database.transaction() as session:
                row = await session.get(NotificationOutbox, args['item_id'])
                assert (row.status, row.version, row.attempts) == ('sending', 1, 1)
                assert row.payload == {'secret': 'never-export'}
            await NotificationQueue(database).quarantine(**args)
            with pytest.raises(RuntimeError, match='archival'):
                migration.downgrade()
    asyncio.run(run())
