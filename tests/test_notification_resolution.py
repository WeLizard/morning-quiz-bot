"""Operator reconciliation acceptance against isolated real PostgreSQL."""
import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from scripts.audit_notification_outbox import summarize
from storage.models import NotificationOutbox, NotificationResolution
from storage.notifications import NotificationQueue, NotificationResolutionConflict
from tests.local_database import isolated_database
from tests.test_postgres_members import pg_env


async def uncertain_item(database, *, key='one'):
    async with database.transaction() as session:
        await NotificationQueue.enqueue_in(session, kind='operator-test', dedupe_key=key,
                                           chat_id=-100, payload={'secret': 'never-export'})
    queue = NotificationQueue(database)
    item = await queue.claim('constant-worker')
    assert await queue.uncertain(item['id'], 'constant-worker', 'TimeoutError', claim_version=item['claim_version'])
    return item['id']


def request(item_id, *, action_id='00000000-0000-4000-8000-000000000001', operator_id='operator:a'):
    return dict(item_id=item_id, action_id=action_id, operator_id=operator_id,
                expected_version=2, decision='confirmed_delivered',
                reason='Проверено оператором',
                evidence={'chat_id': -100, 'message_id': 42,
                          'verification_method': 'manual Telegram history inspection'})


def test_resolution_two_operators_replay_conflict_and_never_reclaim(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            item_id = await uncertain_item(database)
            queue = NotificationQueue(database)
            first = request(item_id)
            second = request(item_id, action_id=str(uuid4()), operator_id='operator:b')
            results = await asyncio.gather(queue.resolve(**first), queue.resolve(**second),
                                           return_exceptions=True)
            assert sum(isinstance(result, dict) for result in results) == 1
            assert sum(isinstance(result, NotificationResolutionConflict) for result in results) == 1
            winner = first if isinstance(results[0], dict) else second
            receipt = next(result for result in results if isinstance(result, dict))
            assert await queue.resolve(**winner) == receipt
            with pytest.raises(NotificationResolutionConflict, match='action_id'):
                await queue.resolve(**dict(winner, reason='changed'))
            assert await queue.claim('constant-worker', now=datetime.now(timezone.utc) + timedelta(days=90)) is None
            assert not await queue.delivered(item_id, 'constant-worker', claim_version=1)
            assert not await queue.retry_after(item_id, 'constant-worker', 0, claim_version=1)
            assert not await queue.uncertain(item_id, 'constant-worker', 'late-error', claim_version=1)
            async with database.transaction() as session:
                row = await session.get(NotificationOutbox, item_id)
                assert (row.status, row.version, row.attempts) == ('resolved', 3, 1)
                assert row.delivered_at is None and row.last_error == 'TimeoutError'
                saved = await session.scalar(select(NotificationResolution))
                assert saved.evidence == winner['evidence'] and saved.reason == winner['reason']
                assert await session.scalar(select(func.count()).select_from(NotificationResolution)) == 1
                report = summarize([row])
            assert report['counts']['resolved'] == 1
            assert report['other_statuses'] == {}
            assert 'never-export' not in json.dumps(report)
            assert 'evidence' not in json.dumps(report)
            assert 'payload' not in receipt
            async with database.transaction() as session:
                await session.execute(delete(NotificationOutbox).where(NotificationOutbox.id == item_id))
            assert await queue.resolve(**winner) == receipt
    asyncio.run(run())


def test_action_replay_serializes_and_cannot_target_another_notification(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            first_id = await uncertain_item(database)
            second_id = await uncertain_item(database, key='two')
            queue = NotificationQueue(database)
            args = request(first_id)
            a, b = await asyncio.gather(queue.resolve(**args), queue.resolve(**args))
            assert a == b
            with pytest.raises(NotificationResolutionConflict, match='action_id'):
                await queue.resolve(**request(second_id))
            async with database.transaction() as session:
                assert (await session.get(NotificationOutbox, second_id)).status == 'uncertain'
    asyncio.run(run())


def test_stale_sending_reject_invalid_evidence_and_atomic_rollback(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            item_id = await uncertain_item(database)
            queue = NotificationQueue(database)
            args = request(item_id)
            with pytest.raises(ValueError, match='UUID'):
                await queue.resolve(**dict(args, action_id='not-a-uuid'))
            with pytest.raises(ValueError, match='оператора'):
                await queue.resolve(**dict(args, reason='   '))
            with pytest.raises(NotificationResolutionConflict, match='Версия'):
                await queue.resolve(**dict(args, expected_version=1))
            with pytest.raises(ValueError, match='chat_id'):
                await queue.resolve(**dict(args, evidence={'message_id': 42}))
            with pytest.raises(ValueError, match='другому чату'):
                await queue.resolve(**dict(args, evidence=dict(args['evidence'], chat_id=-101)))
            with pytest.raises(RuntimeError, match='rollback'):
                async with database.transaction() as session:
                    await queue.resolve_in(session, **args)
                    raise RuntimeError('rollback')
            async with database.transaction() as session:
                assert (await session.get(NotificationOutbox, item_id)).status == 'uncertain'
                assert await session.get(NotificationResolution, args['action_id']) is None
            await queue.resolve(**dict(args, decision='closed_without_resend',
                                       evidence={'verification_method': 'review', 'note': 'Delivery unverifiable'}))
            async with database.transaction() as session:
                await queue.enqueue_in(session, kind='operator-test', dedupe_key='sending', payload={})
            sending = await queue.claim('constant-worker')
            async with database.transaction() as session:
                row = await session.get(NotificationOutbox, sending['id'])
                row.claimed_at = datetime.now(timezone.utc) - timedelta(days=90)
            with pytest.raises(NotificationResolutionConflict, match='uncertain'):
                await queue.resolve(**dict(request(sending['id'], action_id=str(uuid4())), expected_version=1))
            assert await queue.claim('another-worker', now=datetime.now(timezone.utc) + timedelta(days=90)) is None
    asyncio.run(run())


def test_worker_transitions_increment_version(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            queue = NotificationQueue(database)
            async with database.transaction() as session:
                await queue.enqueue_in(session, kind='test', dedupe_key='versions', payload={})
            item = await queue.claim('worker')
            assert await queue.retry_after(item['id'], 'worker', 0, claim_version=item['claim_version'])
            item = await queue.claim('worker')
            assert await queue.delivered(item['id'], 'worker', claim_version=item['claim_version'])
            async with database.transaction() as session:
                assert (await session.get(NotificationOutbox, item['id'])).version == 4
    asyncio.run(run())


def test_resolve_in_refreshes_previously_loaded_state_under_lock(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            item_id = await uncertain_item(database)
            queue = NotificationQueue(database)
            async with database.transaction() as session:
                observed = await session.get(NotificationOutbox, item_id)
                assert observed.status == 'uncertain'
                await queue.resolve(**request(item_id))
                with pytest.raises(NotificationResolutionConflict, match='Версия'):
                    await queue.resolve_in(session, **request(item_id, action_id=str(uuid4())))
                assert observed.status == 'resolved' and observed.version == 3
            async with database.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(NotificationResolution)) == 1
    asyncio.run(run())


def test_additive_migration_preserves_existing_rows_and_receipts(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            path = Path(__file__).resolve().parents[1] / 'alembic/versions/20261009_0022_notification_resolution.py'
            spec = importlib.util.spec_from_file_location('resolution_migration', path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            async with database.engine.begin() as connection:
                await connection.exec_driver_sql('DROP TABLE notification_resolutions')
                await connection.exec_driver_sql('ALTER TABLE notification_outbox DROP COLUMN version, DROP COLUMN resolved_at')
                await connection.exec_driver_sql("INSERT INTO notification_outbox (id,kind,payload,dedupe_key,status) VALUES ('legacy','test','{}','legacy','uncertain')")
                def apply(sync_connection):
                    from alembic.migration import MigrationContext
                    from alembic.operations import Operations
                    with Operations.context(MigrationContext.configure(sync_connection)):
                        migration.upgrade()
                await connection.run_sync(apply)
            async with database.transaction() as session:
                row = await session.get(NotificationOutbox, 'legacy')
                assert (row.status, row.version, row.payload) == ('uncertain', 0, {})
            await NotificationQueue(database).resolve(**dict(request('legacy'), expected_version=0))
            with pytest.raises(RuntimeError, match='archival'):
                migration.downgrade()
    asyncio.run(run())
