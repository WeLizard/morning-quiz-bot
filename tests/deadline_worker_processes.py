"""Entry points of the spawned deadline-worker processes.

Kept apart from ``test_game_worker_concurrency`` on purpose: a ``spawn`` child
imports the module that defines its target, and the test module pulls in the
whole application. Here every heavy import is lazy, so a child starts fast and
the tests do not depend on how slow the machine is.
"""
import asyncio

# A safety net against a hung child, never a performance assertion: the tests
# wait for the child's own result and only fall back to this on a real hang.
HANG_GUARD_SECONDS = 180


def _process_worker_once(database_url, schema, barrier, results, now=None):
    """Run one real worker pass in a separate OS process and isolated schema."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from application.game_deadlines import GameDeadlineProcessor
    from storage.database import Database, DatabaseSettings

    async def run():
        database = Database(DatabaseSettings(url=database_url))
        await database.engine.dispose()
        engine = create_async_engine(
            database_url,
            connect_args={'server_settings': {'search_path': f'"{schema}",public'}},
        )
        database.engine = engine
        database.session_factory = async_sessionmaker(
            engine, expire_on_commit=False, autoflush=False,
        )

        class SynchronizedWorker(GameDeadlineProcessor):
            async def _apply_one(self, mode, chat_id, operation):
                await asyncio.to_thread(barrier.wait, HANG_GUARD_SECONDS)
                return await super()._apply_one(mode, chat_id, operation)

        try:
            await database.check_connection()
            return await SynchronizedWorker(database).run_once(now=now)
        finally:
            await database.dispose()

    try:
        results.put(('ok', asyncio.run(run())))
    except BaseException as error:
        results.put(('error', f'{type(error).__name__}: {error}'))


def _process_worker_once_without_barrier(database_url, schema, results, now=None):
    """A fresh process must observe durable state without replaying it."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from application.game_deadlines import GameDeadlineProcessor
    from storage.database import Database, DatabaseSettings

    async def run():
        database = Database(DatabaseSettings(url=database_url))
        await database.engine.dispose()
        engine = create_async_engine(
            database_url,
            connect_args={'server_settings': {'search_path': f'"{schema}",public'}},
        )
        database.engine = engine
        database.session_factory = async_sessionmaker(
            engine, expire_on_commit=False, autoflush=False,
        )
        try:
            await database.check_connection()
            return await GameDeadlineProcessor(database).run_once(now=now)
        finally:
            await database.dispose()

    try:
        results.put(('ok', asyncio.run(run())))
    except BaseException as error:
        results.put(('error', f'{type(error).__name__}: {error}'))
