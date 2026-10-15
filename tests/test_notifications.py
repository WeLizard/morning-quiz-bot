import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from telegram.error import RetryAfter, TelegramError

from handlers.mafia_handlers import MafiaHandlers
from storage.models import NotificationOutbox
from storage.notifications import NotificationQueue
from tests.local_database import isolated_database
from tests.test_postgres_members import pg_env


def _lobby():
    return {
        'status': 'day',
        'revision': 4,
        'round': 1,
        'players': [{'name': 'Player', 'ready': True, 'alive': True}],
        'can_start': False,
        'can_advance': False,
    }


def test_notification_outbox_deduplicates_claims_and_completes(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            async with database.transaction() as session:
                first = await NotificationQueue.enqueue_in(
                    session, kind='mafia.phase', dedupe_key='phase:one',
                    payload={'lobby': _lobby()}, chat_id=-100,
                )
                duplicate = await NotificationQueue.enqueue_in(
                    session, kind='mafia.phase', dedupe_key='phase:one',
                    payload={'lobby': _lobby()}, chat_id=-100,
                )
                await NotificationQueue.enqueue_in(
                    session, kind='future.mode', dedupe_key='future:one',
                    payload={'event': 'ready'}, chat_id=-100,
                )
            assert first is True and duplicate is False

            queue = NotificationQueue(database)

            async def claim(worker):
                return await queue.claim(worker, kinds={'mafia.phase'})

            claims = await asyncio.gather(claim('worker:a'), claim('worker:b'))
            claimed = [item for item in claims if item is not None]
            assert len(claimed) == 1
            item = claimed[0]
            worker = 'worker:a' if claims[0] else 'worker:b'
            assert item['attempts'] == 1 and item['kind'] == 'mafia.phase'
            assert await queue.delivered(item['id'], worker, claim_version=item['claim_version']) is True
            assert await queue.claim('worker:c', kinds={'mafia.phase'}) is None

            async with database.transaction() as session:
                rows = (await session.scalars(
                    select(NotificationOutbox).order_by(NotificationOutbox.kind)
                )).all()
                assert [(row.kind, row.status) for row in rows] == [
                    ('future.mode', 'pending'), ('mafia.phase', 'delivered')
                ]

    asyncio.run(run())


@pytest.mark.parametrize('completion', ['delivered', 'retry_after', 'uncertain'])
def test_old_claim_cannot_complete_new_attempt_with_same_worker_id(pg_env, completion):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            async with database.transaction() as session:
                await NotificationQueue.enqueue_in(
                    session, kind='test', dedupe_key='fenced-claim', payload={},
                )
            queue = NotificationQueue(database)
            old = await queue.claim('constant-worker')
            assert old['claim_version'] == 1
            assert await queue.retry_after(
                old['id'], 'constant-worker', 0, claim_version=old['claim_version'],
            )
            current = await queue.claim('constant-worker')
            assert current['id'] == old['id']
            assert current['claim_version'] == 3 and current['attempts'] == 2
            async with database.transaction() as session:
                row = await session.get(NotificationOutbox, current['id'])
                before = (row.status, row.version, row.attempts, row.claimed_by,
                          row.claimed_at, row.available_at, row.delivered_at, row.last_error)
            args = {'delivered': (), 'retry_after': (3600,), 'uncertain': ('LateError',)}
            assert not await getattr(queue, completion)(
                old['id'], 'constant-worker', *args[completion],
                claim_version=old['claim_version'],
            )
            async with database.transaction() as session:
                row = await session.get(NotificationOutbox, current['id'])
                assert (row.status, row.version, row.attempts, row.claimed_by,
                        row.claimed_at, row.available_at, row.delivered_at, row.last_error) == before
            assert await getattr(queue, completion)(
                current['id'], 'constant-worker', *args[completion],
                claim_version=current['claim_version'],
            )
            assert not await getattr(queue, completion)(
                current['id'], 'constant-worker', *args[completion],
                claim_version=current['claim_version'],
            )
            async with database.transaction() as session:
                row = await session.get(NotificationOutbox, current['id'])
                assert row.version == 4
                assert row.status == {'delivered': 'delivered', 'retry_after': 'pending',
                                      'uncertain': 'uncertain'}[completion]
    asyncio.run(run())


def test_telegram_delivery_distinguishes_retry_after_from_uncertain_failure(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            async with database.transaction() as session:
                await NotificationQueue.enqueue_in(
                    session, kind='mafia.phase', dedupe_key='phase:retry',
                    payload={'lobby': _lobby()}, chat_id=-101,
                )
            retry_bot = SimpleNamespace(
                username='MorningQuizTestBot',
                send_message=AsyncMock(side_effect=RetryAfter(5)),
            )
            await MafiaHandlers(database)._deliver_notifications(SimpleNamespace(bot=retry_bot))
            async with database.transaction() as session:
                row = await session.scalar(select(NotificationOutbox))
                assert row.status == 'pending' and row.attempts == 1
                assert row.last_error == 'RetryAfter'

            async with database.transaction() as session:
                row = await session.scalar(select(NotificationOutbox))
                # Explicitly make the synthetic retry due without sleeping.
                from datetime import datetime, timezone
                row.available_at = datetime.now(timezone.utc)
            failed_bot = SimpleNamespace(
                username='MorningQuizTestBot',
                send_message=AsyncMock(side_effect=TelegramError('connection lost')),
            )
            await MafiaHandlers(database)._deliver_notifications(SimpleNamespace(bot=failed_bot))
            async with database.transaction() as session:
                row = await session.scalar(select(NotificationOutbox))
                assert row.status == 'uncertain' and row.attempts == 2
                assert row.last_error == 'TelegramError'

    asyncio.run(run())
