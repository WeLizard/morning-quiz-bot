import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from telegram.error import BadRequest, RetryAfter, TimedOut

from tests.test_postgres_members import CHAT, pg_env, scenario
from tests.test_postgres_reads_settings import data_manager
from storage.cleanup import CleanupQueue
from storage.models import MessageCleanupItem
from storage.settings import SettingsService
from storage.repositories import OperationalRepository
from storage.runtime import PostgresRuntimeStorage
from state import BotState


def past():
    return datetime.now(timezone.utc) - timedelta(minutes=1)


def test_enqueue_ack_order_and_stale_snapshot_cannot_resurrect_or_erase(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            queue = CleanupQueue(db)
            await queue.acknowledge(CHAT, 1)
            await queue.enqueue(CHAT, 1, past())  # Delayed old enqueue after acknowledgement.
            await asyncio.gather(queue.enqueue(CHAT, 2, past()), queue.enqueue(CHAT, 3, past()))
            assert {row[1] for row in await queue.due()} == {2, 3}
            with pytest.raises(RuntimeError, match="snapshots"):
                await PostgresRuntimeStorage(db).replace_cleanup_queue({})
            manager = data_manager(db)
            manager.state.generic_messages_to_delete = {CHAT: {1: 0}}
            manager.save_messages_to_delete()
            await manager.save_all_data_async()
            assert {row[1] for row in await queue.due()} == {2, 3}
    asyncio.run(run())


def test_worker_preserves_deadline_across_restart_and_acknowledges_only_success(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            queue = CleanupQueue(db)
            future = datetime.now(timezone.utc) + timedelta(minutes=1)
            await queue.enqueue(CHAT, 1, past())
            await queue.enqueue(CHAT, 2, future)
            await queue.enqueue(CHAT, 3, past())
            bot = SimpleNamespace(delete_message=AsyncMock(side_effect=[TimedOut(), True]))
            assert await CleanupQueue(db).process_due(bot) == 1
            async with db.transaction() as session:
                failed = await session.get(MessageCleanupItem, (CHAT, 1))
                assert failed.payload["state"] == "pending" and failed.delete_after > datetime.now(timezone.utc)
                assert (await session.get(MessageCleanupItem, (CHAT, 2))).delete_after == future
                assert (await session.get(MessageCleanupItem, (CHAT, 3))).payload["state"] == "done"
            assert await queue.due() == []
    asyncio.run(run())


@pytest.mark.parametrize("error,completed", [(BadRequest("Message to delete not found"), 1),
    (BadRequest("message can't be deleted"), 1), (BadRequest("Chat not found"), 0)])
def test_worker_distinguishes_terminal_message_errors_from_retryable_errors(pg_env, error, completed):
    async def run():
        async with scenario(pg_env) as db:
            queue = CleanupQueue(db)
            await queue.enqueue(CHAT, 1, past())
            assert await queue.process_due(SimpleNamespace(delete_message=AsyncMock(side_effect=error))) == completed
            async with db.transaction() as session:
                assert (await session.get(MessageCleanupItem, (CHAT, 1))).payload["state"] == ("done" if completed else "pending")
    asyncio.run(run())


def test_rate_limit_stops_batch_and_survives_worker_restart(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            queue = CleanupQueue(db)
            await queue.enqueue(CHAT, 1, past())
            await queue.enqueue(CHAT, 2, past())
            bot = SimpleNamespace(delete_message=AsyncMock(side_effect=RetryAfter(60)))
            assert await queue.process_due(bot) == 0
            bot.delete_message.assert_awaited_once()
            assert await CleanupQueue(db).process_due(bot) == 0
            bot.delete_message.assert_awaited_once()
            assert await queue.due() == []
            assert len(await queue.due(now=datetime.now(timezone.utc) + timedelta(seconds=61))) == 2
    asyncio.run(run())


def test_cleanup_respects_current_settings_and_keeps_disabled_work(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            queue = CleanupQueue(db)
            settings = SettingsService(db)
            await queue.enqueue(CHAT, 1, past())
            await settings.patch_paths(CHAT, [(('auto_delete_bot_messages',), False)])
            bot = SimpleNamespace(delete_message=AsyncMock())
            assert await queue.process_due(bot) == 0
            bot.delete_message.assert_not_awaited()
            async with db.transaction() as session:
                row = await session.get(MessageCleanupItem, (CHAT, 1))
                assert row.payload['state'] == 'pending'
                row.delete_after = past()
            await settings.patch_paths(CHAT, [(('auto_delete_bot_messages',), True)])
            assert await queue.process_due(bot) == 1
    asyncio.run(run())


def test_legacy_queue_normalization_and_batch_limit(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            async with db.transaction() as session:
                repo = OperationalRepository(session)
                for message_id in range(1, 56):
                    await repo.upsert_cleanup_item({"chat_id": CHAT, "message_id": message_id,
                        "payload": {"legacy_timestamp": (past() - timedelta(minutes=3)).timestamp()}})
            queue = CleanupQueue(db)
            bot = SimpleNamespace(delete_message=AsyncMock())
            assert await queue.process_due(bot) == 50
            assert len(await queue.due()) == 5
            assert await queue.process_due(bot) == 5
            assert await queue.due() == []
    asyncio.run(run())


def test_botstate_uses_addressed_commands_not_snapshot_autosave(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            manager = data_manager(db)
            manager._postgres_write_tasks = set()
            state = BotState(SimpleNamespace())
            state.data_manager = manager
            manager.state = state
            state.add_message_for_deletion(CHAT, 1, delay_seconds=180)
            await manager.flush_postgres_writes()
            async with db.transaction() as session:
                row = await session.get(MessageCleanupItem, (CHAT, 1))
                assert 175 <= (row.delete_after - datetime.now(timezone.utc)).total_seconds() <= 180
            state.remove_message_from_deletion(CHAT, 1)
            state.add_message_for_deletion(CHAT, 1, delay_seconds=1)
            await manager.flush_postgres_writes()
            async with db.transaction() as session:
                assert (await session.get(MessageCleanupItem, (CHAT, 1))).payload["state"] == "done"
    asyncio.run(run())
